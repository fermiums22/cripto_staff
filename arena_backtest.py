"""Minute-resolution proxy of v2 rules, not a replay of unavailable tick quotes."""
import json
import sqlite3
import time
from collections import deque

import agent
import paper_arena as arena

KEYS = ('leadlag_cost_v2', 'breakout_cost_v2', 'rebound_cost_v2')


def exit_hit(bar, entry, spread, tp=arena.TP, sl=arena.SL):
    # OHLC path unknown: adverse stop wins if both levels were touched.
    stop=entry*(1-sl);take=entry*(1+tp)
    bid=lambda p:p*(1-spread/2)
    if bid(bar[1])<=stop:return bid(bar[1]),'stop'
    if bid(bar[1])>=take:return bid(bar[1]),'take'
    if bid(bar[3])<=stop:return stop,'stop'
    if bid(bar[2])>=take:return take,'take'
    return None


def simulate(market, scores, lots, spread, tp=arena.TP, sl=arena.SL, hold_seconds=180):
    symbols=list(market);n=len(market[symbols[0]])
    cash=15.;pos=None;trades=[];curve=[];last_exit=-10**15;peak=15.;drawdown=0.
    for i in range(n):
        ts=market[symbols[0]][i][0]
        if not pos and cash>12 and ts-last_exit>=30000 and i>0:
            candidates=[(scores[s][i-1],s) for s in symbols if scores[s][i-1]>0]
            if candidates:
                _,s=max(candidates);ask=market[s][i][1]*(1+spread/2)
                qty=agent.order_quantity(cash,ask,lots[s])
                if qty>0:
                    entry=ask*(1+agent.SLIP);cost=qty*entry*(1+agent.FEE)
                    cash-=cost;pos=dict(symbol=s,entry=entry,qty=qty,cost=cost,ts=ts)
        if pos:
            bar=market[pos['symbol']][i];hit=exit_hit(bar,pos['entry'],spread,tp,sl)
            if not hit and ((hold_seconds is not None and ts+60000-pos['ts']>=hold_seconds*1000) or i==n-1):
                hit=(bar[4]*(1-spread/2),'end' if i==n-1 else 'timeout')
            if hit:
                price=hit[0]*(1-agent.SLIP);proceeds=pos['qty']*price*(1-agent.FEE)
                cash+=proceeds
                trades.append(dict(pnl=proceeds-pos['cost'],reason=hit[1],
                    fees=agent.FEE*pos['qty']*(pos['entry']+price),hold_seconds=(ts+60000-pos['ts'])/1000))
                # Conservative cooldown from candle end: exact intrabar exit time unknown.
                last_exit=ts+60000;pos=None
        equity=cash+(pos['qty']*market[pos['symbol']][i][4]*(1-spread/2)*(1-agent.SLIP)*(1-agent.FEE) if pos else 0)
        peak=max(peak,equity);drawdown=max(drawdown,100*(1-equity/peak))
        if i%60==0 or i==n-1:curve.append([ts+60000,equity])
    return dict(equity=equity,return_pct=(equity/15-1)*100,trades=len(trades),
        wins=sum(t['pnl']>0 for t in trades),fees=sum(t['fees'] for t in trades),
        max_drawdown_pct=drawdown,loss_limit=cash<=12,curve=curve,
        mean_hold_seconds=sum(t['hold_seconds'] for t in trades)/len(trades) if trades else None,
        exits={r:sum(t['reason']==r for t in trades) for r in ('stop','take','timeout','end')})


def run():
    db=sqlite3.connect('file:'+str(agent.DATA/'research.sqlite3')+'?mode=ro',uri=True)
    end=min(db.execute('SELECT max(ts) FROM bars WHERE symbol=?',(s,)).fetchone()[0] for s in agent.SYMBOLS)
    start=end-30*86400000+60000
    market={s:db.execute('SELECT ts,open,high,low,close,volume FROM bars WHERE symbol=? AND ts BETWEEN ? AND ? ORDER BY ts',(s,start,end)).fetchall() for s in agent.SYMBOLS}
    db.close()
    expected=list(range(start,end+1,60000))
    if any([b[0] for b in bars]!=expected for bars in market.values()):
        raise ValueError('Missing aligned minute candles')
    lots={s:agent.api('instruments-info',category='spot',symbol=s)['result']['list'][0]['lotSizeFilter'] for s in market}
    results={}
    for label,spread in [('base',.0002),('wide_spread',.0006)]:
        history={s:deque(maxlen=4) for s in market}
        scores={k:{s:[] for s in market} for k in KEYS}
        for i in range(len(expected)):
            quotes={s:dict(ts=bars[i][0]+59999,bid=bars[i][4]*(1-spread/2),ask=bars[i][4]*(1+spread/2)) for s,bars in market.items()}
            for k in KEYS:
                for s in market:scores[k][s].append(arena.cost_signal(k,s,history,quotes,cadence_ms=60000))
            # Add the current close only after computing all current signals.
            for s,bars in market.items():history[s].append((bars[i][0]+59999,bars[i][4]))
        results[label]={k:dict(name=arena.STRATEGIES[k][0],**simulate(market,scores[k],lots,spread)) for k in KEYS}
    report=dict(created_ms=int(time.time()*1000),start_ms=start,end_ms=end+60000,
        resolution='minute_proxy',fee_per_side=agent.FEE,slippage_per_side=agent.SLIP,
        assumed_spreads=dict(base=.0002,wide_spread=.0006),results=results,
        notes='Minute-close proxy; no historical bid/ask or queue. Next-open entry; stop-first OHLC. Current lot rules. Independent $15 per strategy, shared across BTC/ETH/SOL. 20% loss halt. Previously inspected history, not untouched validation. No automatic promotion.')
    path=agent.ARTIFACTS/'arena_backtest.json';path.parent.mkdir(exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(report),encoding='utf-8');tmp.replace(path)
    print(json.dumps({label:{k:{f:r[f] for f in ('return_pct','trades','wins','loss_limit')} for k,r in rows.items()} for label,rows in results.items()}))


if __name__=='__main__':run()
