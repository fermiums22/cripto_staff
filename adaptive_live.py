"""Persistent public-data PAPER worker. No private API, orders, or credentials."""
import argparse
import copy
import hashlib
import json
import math
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
import agent
from adaptive_engine import STEP, Wallet, features, choose, summary
from adaptive_research import write

PUBLIC_ENDPOINTS = frozenset(('kline','tickers','instruments-info','risk-limit','funding/history'))


def public(endpoint, **params):
    if endpoint not in PUBLIC_ENDPOINTS:
        raise ValueError('PAPER public endpoint only')
    return agent.api(endpoint,category='linear',**params)


def paused():
    path = agent.DATA/'agent.sqlite3'
    if not path.exists():
        return True
    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=5) as db:
        row = db.execute("SELECT value FROM state WHERE key='control'").fetchone()
        return bool(row and json.loads(row[0]).get('paused',False))


def fresh_quote(response, now_ms):
    stamp = int(response['time'])
    if abs(now_ms-stamp)>30000:
        raise ValueError('Stale exchange quote')
    result = {}
    for row in response['result']['list']:
        bid,ask,mark = (float(row.get(k) or 0) for k in ('bid1Price','ask1Price','markPrice'))
        if all(math.isfinite(v) and v>0 for v in (bid,ask,mark)) and bid<=ask:
            result[row['symbol']] = dict(bid=bid,ask=ask,mark=mark,spread=(ask-bid)/((ask+bid)/2))
    return stamp,result


def closed_features(symbol, now_ms):
    data = public('kline',symbol=symbol,interval='15',limit=65)
    bars = sorted(([int(v[0]),*map(float,v[1:6])] for v in data['result']['list'] if int(v[0])+STEP<=now_ms),key=lambda b:b[0])
    if not bars or not 0<=now_ms-bars[-1][0]-STEP<=STEP:
        return symbol,None
    return symbol,features(bars,len(bars)-1)


def event_schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)')


def persist_cycle(db, previous, working, selected):
    """Wallet changes and their notification outbox commit or roll back together."""
    before = previous['wallet']; after = working['wallet']; events = []
    if not before['position'] and after['position']:
        p = after['position']
        payload = {k:p[k] for k in ('symbol','side','entry','qty','margin','fees','reason','opened_ms')}
        events.append((p['opened_ms'],'paper_entry',payload))
    for trade in after['trades'][len(before['trades']):]:
        events.append((trade['closed_ms'],'paper_exit',dict(trade)))
    with db:
        db.execute('INSERT OR REPLACE INTO state VALUES (1,?)',(json.dumps(working,allow_nan=False),))
        for ts,kind,payload in events:
            payload.update(strategy='adaptive',strategy_name=selected)
            db.execute('INSERT INTO events(ts,kind,payload) VALUES (?,?,?)',
                       (ts,kind,json.dumps(payload,ensure_ascii=False,allow_nan=False)))


def run(once=False):
    import fcntl  # Server worker is Linux; one writer including manual --once runs.
    agent.DATA.mkdir(exist_ok=True); agent.ARTIFACTS.mkdir(exist_ok=True)
    lock = (agent.DATA/'adaptive.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    report = json.loads((agent.ARTIFACTS/'adaptive_research.json').read_text())
    protocol = report['protocol']; selected = protocol['selected']
    config = selected['config'] if selected else dict(family='adaptive',families=[],leverage=1)
    if config.get('leverage',1)!=1 or config.get('pyramid'):
        raise ValueError('Live PAPER restricted to 1x without pyramiding')
    if hashlib.sha256((agent.ROOT/'adaptive_engine.py').read_bytes()).hexdigest()!=protocol['code_sha256']:
        raise ValueError('Engine differs from frozen research')
    identity = hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
    db = sqlite3.connect(agent.DATA/'adaptive.sqlite3',timeout=10)
    db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA synchronous=FULL')
    db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL)')
    event_schema(db)
    row = db.execute('SELECT payload FROM state WHERE id=1').fetchone()
    saved = json.loads(row[0]) if row else dict(identity=identity,wallet=Wallet(config).s,last_signal_ms=0,
        funding_through_ms=0,started_ms=int(time.time()*1000))
    if saved['identity']!=identity:
        raise ValueError('Persisted wallet config differs; refusing reset')
    observations = {}; feature_slot = None; constraints = {}; constraint_ms = 0
    while True:
        try:
            now = int(time.time()*1000)
            if now-constraint_ms>4*3600000:
                def constraints_for(symbol):
                    inst = public('instruments-info',symbol=symbol)['result']['list'][0]
                    risks = public('risk-limit',symbol=symbol)['result']['list']
                    risk = min(risks,key=lambda r:float(r['riskLimitValue']))
                    if inst['status']!='Trading' or inst.get('symbolType'):
                        return symbol,None
                    return symbol,(inst,risk)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    constraints = dict(pool.map(constraints_for,protocol['symbols']))
                constraint_ms = int(time.time()*1000)
            if feature_slot!=now//STEP:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    observations = dict(pool.map(lambda s:closed_features(s,now),protocol['symbols']))
                feature_slot = now//STEP
            response = public('tickers'); now = int(time.time()*1000)
            quote_ms,quotes = fresh_quote(response,now)
            working = copy.deepcopy(saved); wallet = Wallet(config,state=working['wallet'])
            p = wallet.s['position']; existed = bool(p)
            if p:
                quote = quotes.get(p['symbol'])
                if not quote: raise ValueError('Missing held symbol quote')
                since = max(p['opened_ms'],working['funding_through_ms'])
                if quote_ms-since>7*86400000:
                    raise ValueError('Funding gap requires audit')
                rates = public('funding/history',symbol=p['symbol'],startTime=since+1,endTime=quote_ms,limit=200)['result']['list']
                if len(rates)>=200: raise ValueError('Funding pagination required')
                for rate in rates:
                    if since<int(rate['fundingRateTimestamp'])<=quote_ms:
                        wallet.apply_funding(quote['mark'],float(rate['fundingRate']))
                working['funding_through_ms'] = quote_ms
                price = quote['bid'] if p['side']>0 else quote['ask']
                wallet.update([quote_ms,price,price,price,price,0],
                              [quote_ms,quote['mark'],quote['mark'],quote['mark'],quote['mark']],duration=0)
            fresh = {s:f for s,f in observations.items() if f and 0<=quote_ms-f['ts']<STEP
                     and s in quotes and quotes[s]['spread']<=.002 and constraints.get(s)}
            candidate = choose(fresh,config,wallet.costs)
            signal_ms = max((v['ts'] for v in fresh.values()),default=0)
            is_paused = paused()
            if int(time.time()*1000)-quote_ms>30000:
                raise ValueError('Quote expired during funding/control checks')
            if not existed and not wallet.s['position']:
                if not protocol['live_gate']:
                    wallet.s['decision'] = 'collection_only: train/validation profitability gate failed'
                elif is_paused:
                    wallet.s['decision'] = 'paused'
                elif not candidate:
                    wallet.s['decision'] = 'waiting: no eligible signal after estimated costs'
                elif signal_ms>working['last_signal_ms']:
                    quote = quotes[candidate['symbol']]; inst,risk = constraints[candidate['symbol']]
                    price = quote['ask'] if candidate['side']>0 else quote['bid']
                    wallet.enter(candidate,price,quote_ms,inst,risk)
                    working['last_signal_ms'] = signal_ms
                    working['funding_through_ms'] = quote_ms
            equity = wallet.observe(quote_ms)
            wallet.s['curve'] = wallet.s['curve'][-2000:]
            if len(wallet.s['trades'])>=10000: wallet.s['halted'] = True
            working.update(quote_ms=quote_ms,updated_ms=now,candidate=candidate,paused=is_paused,
                observed_symbols=len(fresh),prices={s:quotes[s] for s in fresh},last_error=None)
            persist_cycle(db,saved,working,selected['id'] if selected else 'cash')
            saved = working
            view = dict(mode='LIVE PAPER / no real orders',equity=equity,**working,
                        live_gate=protocol['live_gate'],selected=selected['id'] if selected else 'cash',
                        metrics=summary(wallet),funding_note='Settled rates; polling-time mark is a funding notional approximation.')
            write(agent.ARTIFACTS/'adaptive_live.json',view)
            print(json.dumps(dict(equity=equity,decision=wallet.s['decision'],observed_symbols=len(fresh))),flush=True)
        except Exception as exc:
            # Failed cycles never mutate persisted capital, positions, or cursors.
            view = dict(mode='LIVE PAPER / no real orders',**saved,live_gate=protocol['live_gate'],
                        last_error=type(exc).__name__,error_ms=int(time.time()*1000))
            write(agent.ARTIFACTS/'adaptive_live.json',view)
            print('Cycle failed:',type(exc).__name__,flush=True)
            if once: raise
        if once: break
        time.sleep(15)


if __name__=='__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--once',action='store_true')
    run(parser.parse_args().once)
