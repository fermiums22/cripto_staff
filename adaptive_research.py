"""Frozen chronological research on existing public history, without downloads."""
import gzip
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from datetime import datetime, timezone
import agent
from adaptive_engine import STEP, FAMILIES, SCENARIOS, features, simulate


def write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    tmp.replace(path)


def utc(ms):
    return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()


def audit():
    root = agent.DATA/'portfolio'; manifest = json.loads((root/'manifest.json').read_text())
    market = {}; rows = []; hashes = {}
    for symbol in manifest['symbols']:
        raw = (root/(symbol+'.json.gz')).read_bytes()
        hashes[symbol] = hashlib.sha256(raw).hexdigest()
        data = json.loads(gzip.decompress(raw)); bars = data['trade']; times = [b[0] for b in bars]
        gaps = sum(b-a != STEP for a,b in zip(times,times[1:]))
        aligned = times == [b[0] for b in data['mark']]
        valid = not gaps and aligned and all(features(bars,i) is not None for i in range(32,len(bars)))
        rows.append(dict(symbol=symbol,kind='linear_15m',bars=len(bars),start_utc=utc(times[0]),
                         end_utc=utc(times[-1]+STEP),gaps=gaps,mark_aligned=aligned,eligible=valid))
        if valid and not data['instrument'].get('symbolType'):
            market[symbol] = data
    timeline = [b[0] for b in next(iter(market.values()))['trade']]
    market = {s:d for s,d in market.items() if [b[0] for b in d['trade']]==timeline}
    minutes = []
    dbpath = agent.DATA/'research.sqlite3'
    if dbpath.exists():
        with sqlite3.connect('file:'+str(dbpath)+'?mode=ro',uri=True) as db:
            for s,n,lo,hi in db.execute('SELECT symbol,count(*),min(ts),max(ts) FROM bars GROUP BY symbol'):
                gaps = db.execute('SELECT count(*) FROM (SELECT ts-lag(ts) OVER (ORDER BY ts) AS gap FROM bars WHERE symbol=?) WHERE gap!=60000',(s,)).fetchone()[0]
                minutes.append(dict(symbol=s,bars=n,start_utc=utc(lo),end_utc=utc(hi+60000),gaps=gaps,kind='spot_1m_not_used_for_linear_fills'))
    cached = []
    for name in ('execution_history.json','window_history.json','evolution_history.json'):
        path = agent.DATA/name
        if not path.exists(): continue
        d = json.loads(path.read_text()); bars = d.get('trade',[]) if isinstance(d,dict) else []
        if bars:
            cached.append(dict(file=name,symbol=d.get('symbol',d.get('instrument',{}).get('symbol')),bars=len(bars),
                start_utc=utc(bars[0][0]),end_utc=utc(bars[-1][0]+60000),
                gaps=sum(b[0]-a[0]!=60000 for a,b in zip(bars,bars[1:]))))
    streams = {}; unreadable = 0
    for path in sorted((agent.DATA/'market_stream').glob('*.jsonl.gz')):
        try:
            with gzip.open(path,'rt') as f:
                for line in f:
                    event = json.loads(line); message = event.get('message',{}); topic = message.get('topic','')
                    if '.' not in topic: continue
                    symbol = topic.rsplit('.',1)[1]; stamp = event['received_ms']
                    r = streams.setdefault(symbol,dict(first_ms=stamp,last_ms=stamp,messages=0,trades=0,buy_qty=0.,sell_qty=0.,sessions={}))
                    r['first_ms'] = min(r['first_ms'],stamp); r['last_ms'] = max(r['last_ms'],stamp); r['messages'] += 1
                    session = r['sessions'].setdefault(event['session'],[stamp,stamp]); session[1] = max(session[1],stamp)
                    if topic.startswith('publicTrade.'):
                        for trade in message.get('data',[]):
                            r['trades'] += 1
                            r['buy_qty' if trade['S']=='Buy' else 'sell_qty'] += float(trade['v'])
        except (EOFError,OSError,ValueError):
            unreadable += 1
    for r in streams.values():
        r['start_utc'] = utc(r['first_ms']); r['end_utc'] = utc(r['last_ms'])
        intervals = sorted(r.pop('sessions').values())
        r['session_gap_ms'] = sum(max(0,b[0]-a[1]) for a,b in zip(intervals,intervals[1:]))
        total = r['buy_qty']+r['sell_qty']; r['taker_imbalance'] = (r['buy_qty']-r['sell_qty'])/total if total else None
    return market,dict(fifteen_minute=rows,minute=minutes,cached_linear=cached,stream=streams,
        partial_stream_files=unreadable,hashes=hashes,universe=manifest,
        limitations=['Current surviving-liquidity shortlist, not point-in-time whole-market universe.',
                    'History examined previously: chronological holdout is not pristine.',
                    'Current instrument/risk constraints applied historically; historical rules unavailable.',
                    'Microstructure only in retained sessions; no reconstructed book or participant counts.',
                    'Stream imbalance is diagnostic: insufficient independent history for strategy selection.'])


def compact(result):
    return {k:v for k,v in result.items() if k not in ('records','curve')}


def run():
    destination = agent.ARTIFACTS/'adaptive_research.json'
    if destination.exists():
        print('Frozen report preserved without reevaluating holdout.',flush=True); return
    market,inventory = audit(); symbols = sorted(market)
    if 'BTCUSDT' not in market or 'ETHUSDT' not in market:
        raise ValueError('Missing lead-lag reference data')
    clock = market[symbols[0]]['trade']; n = len(clock); train = n*6//10; validation = n*8//10
    if train < 200 or n-validation < 100: raise ValueError('Insufficient chronological data')
    cached = {s:[features(d['trade'],i) for i in range(n)] for s,d in market.items()}
    candidates = []
    for family in (*FAMILIES,'adaptive'):
        for exit_mode in ('early','trail'):
            for threshold in (.003,.006):
                config = dict(family=family,families=list(FAMILIES[:4]) if family=='adaptive' else [family],
                    exit=exit_mode,threshold=threshold,leverage=1,risk_fraction=.02,stop=.02,take=.008,
                    hold_bars=32,volume=True,regime=True,pyramid=False)
                training = simulate(market,cached,config,33,train)
                valid = simulate(market,cached,config,train,validation)
                candidates.append(dict(id=f'{family}_{exit_mode}_{threshold}',config=config,train=compact(training),validation=compact(valid)))
    eligible = [r for r in candidates if r['train']['trades']>=10 and r['validation']['trades']>=5
                and r['validation']['max_drawdown_pct']<30 and not r['validation']['liquidations']]
    selected = max(eligible,key=lambda r:(r['validation']['net']-.03*r['validation']['max_drawdown_pct'],r['id'])) if eligible else None
    protocol = dict(created_ms=int(time.time()*1000),symbols=symbols,data_hashes=inventory['hashes'],
        train=[utc(clock[33][0]),utc(clock[train][0])],validation=[utc(clock[train][0]),utc(clock[validation][0])],
        test=[utc(clock[validation][0]),utc(clock[-1][0]+STEP)],selected=selected,
        selection='Train >=10 trades; validation >=5, DD<30%, no liquidation; maximize validation net - .03*DD.',
        live_gate=bool(selected and selected['train']['net']>0 and selected['validation']['net']>0),
        costs=SCENARIOS,fee_note='SOL taker .001 / maker .00036 from prior verified report; other symbols scenario only. All fills taker.',
        execution='15m OHLC; next open; stop before target; mark liquidation first; next-bar trail; isolated bankruptcy cap; gap stops at open.',
        code_sha256=hashlib.sha256(Path(__file__).with_name('adaptive_engine.py').read_bytes()).hexdigest())
    frozen = agent.ARTIFACTS/'adaptive_protocol.json'
    if frozen.exists():
        prior = json.loads(frozen.read_text())
        if prior['data_hashes']!=protocol['data_hashes'] or prior['selected']!=protocol['selected']:
            raise ValueError('Frozen selection differs; refusing holdout reuse')
        protocol = prior
    else:
        write(frozen,protocol)
    print('Selection frozen:',selected['id'] if selected else 'cash',flush=True)
    scenarios = {}; ablations = []; controls = []
    if selected:
        config = selected['config']
        variants = [('no_volume',dict(volume=False)),('no_regime',dict(regime=False)),
            ('without_btc_eth_signal',dict(families=[f for f in config['families'] if f!='leadlag'])),
            ('early_exit',dict(exit='early')),('trailing_exit',dict(exit='trail'))]
        for name,change in variants:
            result = simulate(market,cached,dict(config,**change),train,validation)
            ablations.append(dict(id=name,period='validation',result=compact(result)))
        for name,costs in SCENARIOS.items(): scenarios[name] = simulate(market,cached,config,validation,n,costs)
        for leverage,pyramid in ((3,False),(10,False),(3,True)):
            r = simulate(market,cached,dict(config,leverage=leverage,pyramid=pyramid),validation,n)
            controls.append(dict(leverage=leverage,pyramid=pyramid,selection_allowed=False,result=compact(r)))
    report = dict(protocol=protocol,inventory=inventory,leaderboard=candidates,scenarios=scenarios,
        ablations=ablations,leverage_controls=controls,cash_benchmark=15,
        hypotheses=['1/4 BTC+ETH lead-lag and validation removal; no universal correlation claim.',
        '2 Impulse continuation and pump exhaustion candidates.',
        '3 Leverage 1/3/10 and winning pyramid stress; live capped at 1.',
        '5 Website/API latency blocked: no paired website receive-time archive.',
        '6 News ablation blocked: inadequate point-in-time news history.',
        '7 Cost gate and early TP vs trailing; profit never guaranteed.',
        '8 Timestamp-seeded random direction after displacement; TP .8%, SL 2%.',
        '9 Past-only regime and validation removal; regime outcomes descriptive.',
        '10 Volume ablation and retained-stream imbalance audit; no people counts.'],
        live_policy='Entries require positive train AND validation, independent of holdout. Otherwise collection only.',
        completed_ms=int(time.time()*1000))
    write(destination,report)
    print(json.dumps(dict(selected=selected['id'] if selected else None,live_gate=protocol['live_gate'],
        scenarios={k:compact(v) for k,v in scenarios.items()})),flush=True)


if __name__=='__main__':
    run()
