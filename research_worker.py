"""Bounded recurring GPU search on real one-minute spot data. Never submits orders."""
import json
import logging
import math
import sqlite3
import time
from datetime import datetime, timezone

import agent

SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT')
CONFIGS = ((0.004, 0.003, 3), (0.006, 0.004, 10), (0.010, 0.006, 30))


def write_json(path, value):
    path.parent.mkdir(exist_ok=True, parents=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def progress(stage, **values):
    write_json(agent.ARTIFACTS/'research_status.json', dict(stage=stage, updated_ms=int(time.time()*1000), **values))
    logging.info('%s %s', stage, json.dumps(values))


def collect_minutes(db, symbol, days=90):
    cutoff = (int(time.time()*1000)-days*86400000)//60000*60000
    earliest, latest = db.execute('SELECT MIN(ts),MAX(ts) FROM bars WHERE symbol=?', (symbol,)).fetchone()
    # Update tail first, then resume the historical backfill from its last page.
    phases = [(None, latest if latest is not None else cutoff)]
    if earliest is not None and earliest > cutoff:
        phases.append((earliest-1, cutoff))
    for end, stop in phases:
        for page in range(1000):
            params = dict(category='spot', symbol=symbol, interval='1', limit=1000)
            if end is not None:
                params['end'] = end
            result = agent.api('kline', **params)
            raw = result['result']['list']
            if not raw:
                break
            rows = []
            for row in raw:
                ts = int(row[0]); values = list(map(float, row[1:6]))
                if ts < cutoff or ts+60000 > int(result['time']):
                    continue
                o,h,low,c,v = values
                if ts % 60000 or not all(math.isfinite(x) for x in values) or min(o,h,low,c)<=0 or low>min(o,c) or h<max(o,c) or v<0:
                    raise ValueError('Invalid minute candle')
                rows.append((symbol,ts,*values))
            with db:
                db.executemany('INSERT OR IGNORE INTO bars VALUES (?,?,?,?,?,?,?)', rows)
            oldest = min(int(r[0]) for r in raw)
            if oldest <= stop:
                break
            if end is not None and oldest >= end:
                raise RuntimeError('History pagination stalled')
            end = oldest-1
            if page % 10 == 0:
                count = db.execute('SELECT count(*) FROM bars WHERE symbol=?', (symbol,)).fetchone()[0]
                progress('download', symbol=symbol, candles=count, target_days=days)
            time.sleep(0.12)
        else:
            raise RuntimeError('History request bound exceeded')


def matrix(bars):
    import numpy as np
    b = np.asarray(bars, dtype=float); close=b[:,4]
    returns = []
    for lag in (1,3,6,12,24,60,240):
        col=np.zeros(len(b)); col[lag:]=close[lag:]/close[:-lag]-1; returns.append(col)
    avg=np.convolve(b[:,5], np.ones(24)/24, mode='full')[:len(b)]
    # UTC calendar features are known at decision time; no future news is inserted.
    hour=(b[:,0]/3600000)%24; weekday=((b[:,0]//86400000)+3)%7
    return np.column_stack(returns+[(b[:,2]-b[:,3])/close,
         np.divide(b[:,5],avg,out=np.zeros(len(b)),where=avg>0)-1,
         np.sin(hour*2*np.pi/24),np.cos(hour*2*np.pi/24),
         np.sin(weekday*2*np.pi/7),np.cos(weekday*2*np.pi/7)]).astype('float32')


def outcome(bars, opened, config, slip=agent.SLIP, end=None):
    tp,sl,horizon=config
    entry=bars[opened][1]*(1+slip)
    limit=len(bars) if end is None else min(end,len(bars))
    for k in range(opened,min(limit,opened+horizon)):
        bar=bars[k]
        if bar[1]<=entry*(1-sl): price=bar[1]
        elif bar[3]<=entry*(1-sl): price=entry*(1-sl)
        elif bar[2]>=entry*(1+tp): price=entry*(1+tp)
        elif k==opened+horizon-1 or k==limit-1: price=bar[4]
        else: continue
        return k,price*(1-slip),entry
    raise ValueError('No execution candle')


def simulate(bars, scores, start, end, config, threshold, lot, slip=agent.SLIP):
    cash=15.; peak=15.; drawdown=0.; trades=0; wins=0; held=[]; curve=[]
    i=start+1
    while i<end:
        if scores[i-1]<threshold:
            i+=1; continue
        closed,price,entry=outcome(bars,i,config,slip,end)
        step=float(lot['basePrecision'])
        qty=math.floor((cash*.9/(entry*(1+agent.FEE)))/step)*step
        if qty<float(lot['minOrderQty']) or qty*entry<float(lot['minOrderAmt']):
            i+=1; continue
        cost=qty*entry*(1+agent.FEE)
        for k in range(i,closed):
            equity=cash-cost+qty*bars[k][4]*(1-slip)*(1-agent.FEE)
            peak=max(peak,equity); drawdown=max(drawdown,1-equity/peak)
        pnl=qty*price*(1-agent.FEE)-cost
        cash+=pnl; peak=max(peak,cash);drawdown=max(drawdown,1-cash/peak)
        trades+=1;wins+=pnl>0;held.append(closed-i+1)
        curve.append([bars[closed][0]+60000,cash]);i=closed+1
    days=(bars[end-1][0]-bars[start][0]+60000)/86400000
    return dict(return_pct=(cash/15-1)*100,end_usdt=cash,trades=trades,
                max_drawdown_pct=drawdown*100,trades_per_day=trades/days,
                mean_hold_minutes=sum(held)/len(held) if held else None,
                win_rate=wins/trades if trades else None,curve=curve[::max(1,len(curve)//300)])


def run():
    import numpy as np
    agent.DATA.mkdir(exist_ok=True);agent.ARTIFACTS.mkdir(exist_ok=True)
    db=sqlite3.connect(agent.DATA/'research.sqlite3',timeout=20)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS bars(symbol TEXT,ts INTEGER,open REAL,high REAL,low REAL,close REAL,volume REAL,PRIMARY KEY(symbol,ts))')
    for symbol in SYMBOLS: collect_minutes(db,symbol)
    cutoff=int(time.time()*1000)-90*86400000
    market={s:db.execute('SELECT ts,open,high,low,close,volume FROM bars WHERE symbol=? AND ts>=? ORDER BY ts',(s,cutoff)).fetchall() for s in SYMBOLS}
    db.close()
    common=set.intersection(*[set(b[0] for b in rows) for rows in market.values()])
    market={s:[b for b in rows if b[0] in common] for s,rows in market.items()}
    n=len(market['BTCUSDT']);train_end=int(n*.6);test_start=int(n*.8)
    if n<10000 or any(b[0]-a[0]!=60000 for a,b in zip(market['BTCUSDT'],market['BTCUSDT'][1:])):
        raise RuntimeError('Minute history missing or not contiguous')
    matrices={s:matrix(b) for s,b in market.items()}
    candidates={};saved={}; total=len(CONFIGS)*2*len(SYMBOLS);done=0
    for config_index,config in enumerate(CONFIGS):
        horizon=config[2];indices=np.arange(240,train_end-horizon)
        for cross in (False,True):
            key=f'c{config_index}-'+('cross' if cross else 'own')
            predictions={}; models={}
            for symbol,bars in market.items():
                done+=1;progress('training',completed=done-1,total=total,candidate=key,symbol=symbol,candles=n)
                x=matrices[symbol]
                if cross:x=np.column_stack([x,matrices['BTCUSDT'][:,:7],matrices['ETHUSDT'][:,:7]])
                y=[]
                for i in indices:
                    _,sell,buy=outcome(bars,int(i)+1,config)
                    y.append(int(sell*(1-agent.FEE)>buy*(1+agent.FEE)))
                if len(set(y))<2:
                    raise RuntimeError('Insufficient positive/negative training outcomes')
                model=agent.fit_model(x[indices],y)
                pred=np.zeros(n);pred[train_end:]=agent.probabilities(model,x[train_end:])
                predictions[symbol]=pred;models[symbol]=model
            lots={s:agent.api('instruments-info',category='spot',symbol=s)['result']['list'][0]['lotSizeFilter'] for s in SYMBOLS}
            for threshold in (.5,.6,.7):
                name=key+f'-p{threshold}'
                val={s:simulate(b,predictions[s],train_end,test_start,config,threshold,lots[s]) for s,b in market.items()}
                for v in val.values(): v.pop('curve')
                score=sum(v['return_pct'] for v in val.values())/len(val)
                candidates[name]=dict(config=config,threshold=threshold,cross=cross,validation=val,
                                      validation_mean_pct=score,validation_trades=sum(v['trades'] for v in val.values()))
            saved[key]=(predictions,models,lots)
    # Select only on validation. Do not rank/retry candidates against the final period.
    eligible=[k for k,v in candidates.items() if v['validation_trades']>=30]
    winner=max(eligible or candidates,key=lambda k:candidates[k]['validation_mean_pct'])
    chosen=candidates[winner];key=winner.rsplit('-p',1)[0];predictions,models,lots=saved[key]
    result={s:simulate(b,predictions[s],test_start,n,chosen['config'],chosen['threshold'],lots[s]) for s,b in market.items()}
    stress={s:simulate(b,predictions[s],test_start,n,chosen['config'],chosen['threshold'],lots[s],agent.SLIP*2) for s,b in market.items()}
    mean=sum(v['return_pct'] for v in result.values())/len(result)
    stressed=sum(v['return_pct'] for v in stress.values())/len(stress)
    report=dict(created_ms=int(time.time()*1000),candles_per_symbol=n,interval_minutes=1,
                train_end_ms=market['BTCUSDT'][train_end-1][0],test_start_ms=market['BTCUSDT'][test_start][0],
                test_end_ms=market['BTCUSDT'][-1][0],selected=winner,candidates=candidates,test=result,
                test_mean_pct=mean,stress_mean_pct=stressed,
                passes_initial_screen=mean>0 and stressed>0 and sum(v['trades'] for v in result.values())>=30,
                auto_promoted=False,scope='independent $15 spot accounts; no leverage',
                limitations=['Current lot rules applied to history; historical orderbook unavailable',
                             'One-minute OHLC cannot validate sub-minute scalping or limit-order fills',
                             'Repeated daily tests overlap; not independent confirmations',
                             'No real orders or automatic deployment of selected models'])
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    archive=agent.ARTIFACTS/'search-runs'/run_id
    write_json(archive/'result.json',report);write_json(archive/'models.json',models)
    write_json(agent.ARTIFACTS/'search_result.json',report)
    progress('completed',selected=winner,models_trained=done,candidates=len(candidates),
             test_mean_pct=mean,stress_mean_pct=stressed,passes_initial_screen=report['passes_initial_screen'],run_id=run_id)


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    try:run()
    except Exception as exc:
        progress('failed',error=type(exc).__name__+': '+str(exc)[:200])
        raise
