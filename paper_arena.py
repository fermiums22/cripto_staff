"""Parallel unapproved paper experiments on fresh spot quotes; no order API."""
import json
import logging
import math
import time
from collections import deque

import agent

STRATEGIES = {
    'pressure60': ('Дисбаланс лучшей цены · 60 с', 60),
    'momentum60': ('Микроимпульс · 60 с', 60),
    'breakout90': ('Пробой 30 секунд · 90 с', 90),
    'rebound120': ('Отскок после снижения · 120 с', 120),
    'range90': ('Возврат к средней · 90 с', 90),
    'leadlag180': ('Запаздывание за BTC · 180 с', 180),
    'leadlag_cost_v2': ('BTC v2 · фильтр издержек · 180 с', 180),
    'breakout_cost_v2': ('Сильный пробой v2 · 180 с', 180),
    'rebound_cost_v2': ('Глубокий отскок v2 · 180 с', 180),
}
TP = .004
SL = .002


def setup(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS arena_accounts(id TEXT PRIMARY KEY,payload TEXT);
      CREATE TABLE IF NOT EXISTS arena_equity(strategy TEXT,ts INTEGER,value REAL,PRIMARY KEY(strategy,ts));
    ''')
    with db:
        for key, (name, hold) in STRATEGIES.items():
            state=dict(name=name,hold_seconds=hold,cash=15.,position=None,equity=15.,
                       trades=0,wins=0,holding_seconds=0,fees=0.,last_closed_ms=0,
                       peak=15.,max_drawdown_pct=0.,reason='warmup',created_ms=int(time.time()*1000))
            db.execute('INSERT OR IGNORE INTO arena_accounts VALUES (?,?)',(key,json.dumps(state)))


def fetch_quote(symbol):
    d=agent.api('tickers',category='spot',symbol=symbol)
    raw=d['result']['list'][0]
    q=dict(ts=int(d['time']),bid=float(raw['bid1Price']),ask=float(raw['ask1Price']),
           bid_size=float(raw.get('bid1Size') or 0),ask_size=float(raw.get('ask1Size') or 0))
    if not all(math.isfinite(v) for v in q.values()) or not 0<q['bid']<=q['ask']:
        raise ValueError('Invalid quote')
    return q


def signal(strategy, symbol, history, quotes):
    q=quotes[symbol];now=q['ts'];mid=(q['bid']+q['ask'])/2
    if strategy.endswith('_cost_v2'):
        return cost_signal(strategy,symbol,history,quotes)
    previous=[p for p in history[symbol] if 0<now-p[0]<=30000]
    # Book pressure needs no manufactured warm-up prices.
    if strategy=='pressure60':
        total=q['bid_size']+q['ask_size']
        imbalance=(q['bid_size']-q['ask_size'])/total if total else 0
        return imbalance if imbalance>.25 else 0
    if len(previous)<4 or now-previous[0][0]<20000:
        return 0
    prices=[p[1] for p in previous];change=mid/prices[0]-1;last=mid/prices[-1]-1
    if strategy=='momentum60':return change if change>.00015 else 0
    if strategy=='breakout90':return mid/max(prices)-1 if mid>max(prices)*1.00005 else 0
    if strategy=='rebound120':return -change if change<-.00015 and last>0 else 0
    if strategy=='range90':
        deviation=mid/(sum(prices)/len(prices))-1
        return -deviation if deviation<-.0001 and last>=0 else 0
    if strategy=='leadlag180' and symbol!='BTCUSDT' and 'BTCUSDT' in quotes:
        btc=[p for p in history['BTCUSDT'] if 0<now-p[0]<=30000]
        if len(btc)>=4 and now-btc[0][0]>=20000:
            lead=btc[-1][1]/btc[0][1]-1
            return lead-change if lead>.00015 and -.0005<change<lead/2 else 0
    return 0


def cost_signal(strategy, symbol, history, quotes, cadence_ms=5000):
    q=quotes[symbol];now=q['ts'];mid=(q['bid']+q['ask'])/2
    def window(s):
        points=[p for p in history[s] if 0<now-p[0]<=180000]
        if len(points)<(3 if cadence_ms==60000 else 20) or now-points[0][0]<150000 or now-points[-1][0]>3*cadence_ms:
            return []
        if any(b[0]-a[0]>3*cadence_ms for a,b in zip(points,points[1:])):
            return []
        return [p[1] for p in points]
    prices=window(symbol)
    if not prices:return 0
    # Observed movement is a filter, never a prediction of future profit.
    cost=q['ask']/q['bid']*(1+agent.SLIP)*(1+agent.FEE)/((1-agent.SLIP)*(1-agent.FEE))-1
    change=mid/prices[0]-1
    rising=mid>prices[-1]>prices[-2]
    if strategy=='leadlag_cost_v2' and symbol!='BTCUSDT' and 'BTCUSDT' in quotes:
        btc=window('BTCUSDT');bq=quotes['BTCUSDT']
        if not btc or abs(bq['ts']-now)>10000:return 0
        lead=((bq['bid']+bq['ask'])/2)/btc[0]-1
        gap=lead-change
        return gap if lead>1.5*cost and gap>cost and change>0 and rising else 0
    if strategy=='breakout_cost_v2':
        return change if change>1.5*cost and mid>max(prices)*1.0001 and rising else 0
    if strategy=='rebound_cost_v2':
        drop=max(prices)/min(prices)-1
        recovery=mid/min(prices)-1
        return drop if drop>2*cost and .25*cost<recovery<.75*cost and rising else 0
    return 0


def step(db, quotes, history, instruments, now):
    fresh={s:q for s,q in quotes.items() if 0<=now-q['ts']<=10000}
    with db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT value FROM state WHERE key='control'").fetchone()
        paused=json.loads(row[0]).get('paused',False) if row else False
        for key,(name,hold) in STRATEGIES.items():
            state=json.loads(db.execute('SELECT payload FROM arena_accounts WHERE id=?',(key,)).fetchone()[0])
            pos=state['position'];closed=False
            if pos:
                q=fresh.get(pos['symbol'])
                if q and q['ts']>pos['opened_ms']:
                    reason=('stop' if q['bid']<=pos['entry']*(1-SL) else
                            'take' if q['bid']>=pos['entry']*(1+TP) else
                            'timeout' if now-pos['opened_ms']>=hold*1000 else None)
                    if reason:
                        price=q['bid']*(1-agent.SLIP)
                        proceeds=pos['qty']*price*(1-agent.FEE)
                        pnl=proceeds-pos['cost']
                        state['cash']+=proceeds;state['position']=None
                        state['trades']+=1;state['wins']+=int(pnl>0)
                        state['holding_seconds']+=(now-pos['opened_ms'])/1000
                        state['fees']+=pos['qty']*price*agent.FEE
                        state['last_closed_ms']=now;closed=True
                        agent.event(db,now,'paper_exit',{**pos,'strategy':key,'strategy_name':name,
                                    'reason':reason,'proceeds':proceeds,'pnl_usdt':pnl,
                                    'balance_usdt':state['cash'],'exit_price':price})
            if state['position']:
                state['reason']='position_open' if state['position']['symbol'] in fresh else 'stale_quote'
            elif paused:state['reason']='paused'
            elif not fresh:state['reason']='stale_quote'
            elif state['cash']<=12:state['reason']='loss_limit'
            elif now-state['last_closed_ms']<(30000 if key.endswith('_cost_v2') else 10000) or closed:state['reason']='cooldown'
            else:
                state['reason']='waiting_cost_signal' if key.endswith('_cost_v2') else 'waiting_signal'
                candidates=[]
                for symbol,q in fresh.items():
                    spread=q['ask']/q['bid']-1
                    if instruments[symbol]['status']!='Trading' or spread>.0008:
                        continue
                    score=signal(key,symbol,history,fresh)
                    if score>0:candidates.append((score,symbol))
                if candidates:
                    _,symbol=max(candidates);q=fresh[symbol]
                    qty=agent.order_quantity(state['cash'],q['ask'],instruments[symbol]['lotSizeFilter'])
                    if qty<=0:state['reason']='minimum_order'
                    elif q['ask_size']<qty:state['reason']='insufficient_top_liquidity'
                    else:
                        entry=q['ask']*(1+agent.SLIP);cost=qty*entry*(1+agent.FEE)
                        state['cash']-=cost;state['fees']+=qty*entry*agent.FEE
                        pos=dict(symbol=symbol,qty=qty,entry=entry,cost=cost,opened_ms=now,
                                 strategy=key,strategy_name=name,entry_bid=q['bid'],entry_ask=q['ask'],
                                 fee_per_side=agent.FEE,slippage_per_side=agent.SLIP)
                        state['position']=pos;state['reason']='paper_entry'
                        agent.event(db,now,'paper_entry',pos)
            pos=state['position']
            # A missing quote must not fabricate a price/equity observation.
            if not pos or pos['symbol'] in fresh:
                equity=state['cash']+(pos['qty']*fresh[pos['symbol']]['bid']*(1-agent.SLIP)*(1-agent.FEE) if pos else 0)
                state['equity']=equity;state['peak']=max(state['peak'],equity)
                state['max_drawdown_pct']=max(state['max_drawdown_pct'],100*(1-equity/state['peak']))
                db.execute('INSERT OR REPLACE INTO arena_equity VALUES (?,?,?)',(key,now,equity))
            state['updated_ms']=now
            db.execute('UPDATE arena_accounts SET payload=? WHERE id=?',(json.dumps(state),key))
        db.execute("INSERT OR REPLACE INTO state VALUES ('arena_status',?)",
                   (json.dumps(dict(heartbeat_ms=now,paused=paused,fresh_symbols=list(fresh),last_error=None)),))


def run():
    history={s:deque(maxlen=90) for s in agent.SYMBOLS}
    with agent.connect() as db:
        setup(db);instruments={};refreshed=0
        while True:
            began=time.monotonic()
            try:
                if time.time()-refreshed>3600:
                    instruments={s:agent.api('instruments-info',category='spot',symbol=s)['result']['list'][0] for s in agent.SYMBOLS}
                    refreshed=time.time()
                quotes={s:fetch_quote(s) for s in agent.SYMBOLS}
                now=int(time.time()*1000)
                for s,q in quotes.items():
                    if 0<=now-q['ts']<=10000 and (not history[s] or q['ts']>history[s][-1][0]):
                        history[s].append((q['ts'],(q['bid']+q['ask'])/2))
                step(db,quotes,history,instruments,now)
            except Exception as exc:
                logging.exception('Paper arena cycle failed')
                with db:
                    row=db.execute("SELECT value FROM state WHERE key='arena_status'").fetchone()
                    status=json.loads(row[0]) if row else {}
                    status.update(last_error=type(exc).__name__,error_ms=int(time.time()*1000))
                    db.execute("INSERT OR REPLACE INTO state VALUES ('arena_status',?)",(json.dumps(status),))
            time.sleep(max(.1,5-(time.monotonic()-began)))


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    run()
