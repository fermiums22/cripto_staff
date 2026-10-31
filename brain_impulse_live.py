"""Independent public-stream execution audit for three frozen PAPER controls.

Candidate stays CASH: this runner cannot load/promote a model or send orders.
It establishes a working durable live-execution path for subsequent model trials.
No credentials, private endpoints, Telegram, or writes to existing PAPER wallets.
"""
import argparse
from contextlib import closing as close_after
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
import urllib.parse
import urllib.request
import uuid

import websocket
from brain_impulse_data import ImpulseSampler,atomic_json
from brain_impulse_execution import DurablePaper,ExecutionPolicy,policy_digest
from brain_impulse_controls import signals

ROOT=Path(__file__).resolve().parent
SYMBOLS=('BTCUSDT','ETHUSDT','SOLUSDT','DOGEUSDT','XRPUSDT','BNBUSDT')
FILES=('brain_impulse_data.py','brain_impulse_execution.py','brain_impulse_controls.py','brain_impulse_live.py')


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def paused(path):
    try:
        with close_after(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=.1)) as db:
            row=db.execute("SELECT value FROM state WHERE key='control'").fetchone()
        if row is None:return False
        value=json.loads(row[0])
        # Bad data fails closed, including strings masquerading as booleans.
        return value.get('paused',False) is not False
    except (sqlite3.Error,ValueError,AttributeError,TypeError):return True


def instruments():
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    result={}
    for symbol in SYMBOLS:
        params=urllib.parse.urlencode(dict(category='linear',symbol=symbol))
        start=time.time_ns()//1000000
        with opener.open('https://api.bybit.com/v5/market/instruments-info?'+params,timeout=10) as response:
            payload=json.load(response)
        now=time.time_ns()//1000000
        if payload.get('retCode')!=0 or now-start>10000 or abs(now-int(payload['time']))>1500:
            raise ValueError('Instrument request rejected or stale')
        item=payload['result']['list'][0]
        if item['symbol']!=symbol or item['status']!='Trading':raise ValueError('Invalid instrument')
        result[symbol]={k:item[k] for k in ('symbol','status','lotSizeFilter','priceFilter')}
    return result


def prepare(directory):
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/'protocol.json'
    hashes={name:digest(ROOT/name) for name in FILES}
    if not path.exists():
        value=dict(created_ms=time.time_ns()//1000000,source_hashes=hashes,
            policy_sha256=policy_digest(ExecutionPolicy()),controls=['cash','momentum','leadlag_flow'],
            mode='Independent PAPER execution/control audit, no qualified candidate',ready=False,
            limitations=['Taker .0006 and slippage .0003 per side are cost scenarios',
                'No maker queue simulation','Unknown funding invalidates the run',
                '1x insolvency guard is not Bybit maintenance-tier liquidation',
                'Control forecasts are untrained rules, not established expected returns'])
        atomic_json(path,value)
        atomic_json(directory/'frozen.json',dict(protocol_sha256=digest(path)))
    value=json.loads(path.read_text())
    if json.loads((directory/'frozen.json').read_text())['protocol_sha256']!=digest(path):
        raise ValueError('Frozen execution protocol modified')
    if hashes!=value['source_hashes']:raise ValueError('Frozen execution source changed')
    if value['policy_sha256']!=policy_digest(ExecutionPolicy()):raise ValueError('Frozen execution policy changed')
    snapshot=directory/'source';snapshot.mkdir(exist_ok=True)
    for name,expected in hashes.items():
        target=snapshot/name
        if not target.exists():target.write_bytes((ROOT/name).read_bytes())
        if digest(target)!=expected:raise ValueError('Frozen source snapshot mismatch')
    return value,digest(path)


def run(directory,duration=None):
    directory.mkdir(parents=True,exist_ok=True)
    lock=(directory/'worker.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    protocol,identity=prepare(directory)
    accounts={k:DurablePaper(directory/(k+'.sqlite3'),protocol_id=identity+':'+k)
              for k in protocol['controls']}
    states={k:db.state() for k,db in accounts.items()}
    for key in list(os.environ):
        if 'proxy' in key.lower():del os.environ[key]
    started=time.monotonic();stop_at=started+duration if duration is not None else float('inf')
    failures=0;received_messages=0;last_status=0.;closing=False;sampler=None
    try:
        while True:
            ws=None
            try:
                inst=instruments();inst_ms=time.time_ns()//1000000
                atomic_json(directory/('instruments-'+str(inst_ms)+'.json'),dict(received_ms=inst_ms,instruments=inst))
                session=uuid.uuid4().hex;sampler=ImpulseSampler()
                cache={k:{} for k in accounts};next_decision=0;decision_due=None
                last_book={};pause_at=0;is_paused=True
                last_sample_ms=None;connected_ms=inst_ms
                ws=websocket.create_connection('wss://stream.bybit.com/v5/public/linear',timeout=5)
                topics=[f'{kind}.{s}' for s in SYMBOLS for kind in ('orderbook.50','publicTrade','tickers','allLiquidation')]
                for i in range(0,len(topics),10):ws.send(json.dumps(dict(op='subscribe',args=topics[i:i+10])))
                ping=time.monotonic()
                while True:
                    mono=time.monotonic();now=time.time_ns()//1000000
                    if mono>=stop_at and not closing:
                        closing=True
                        for k,db in accounts.items():
                            db.apply('duration-end',dict(type='halt',reason='finite_audit_finished'))
                            states[k]=db.state()
                    if closing and all(not s['position'] and not s['pending'] for s in states.values()):return
                    # A skipped/stale delta invalidates the reconstructed book. A new
                    # snapshot is necessary; waiting forever on deltas cannot repair it.
                    if now-connected_ms>65000 and any(s not in sampler.books for s in ('BTCUSDT','ETHUSDT')):
                        raise RuntimeError('Leader book invalidated; reconnect for fresh snapshots')
                    if last_sample_ms is not None and now-last_sample_ms>20000:
                        raise RuntimeError('Feature continuity lost; reconnect and warm up again')
                    if mono-pause_at>=1:
                        is_paused=paused(ROOT/'data/agent.sqlite3');pause_at=mono
                        if shutil.disk_usage(directory).free<512*1024**2:
                            is_paused=True
                    if mono-ping>=20:ws.send(json.dumps(dict(op='ping')));ping=mono
                    try:raw=ws.recv()
                    except websocket.WebSocketTimeoutException:continue
                    if not raw:raise RuntimeError('Public stream disconnected')
                    now=time.time_ns()//1000000;message=json.loads(raw);received_messages+=1
                    if message.get('success') is False:raise ValueError('Public subscription rejected')
                    row=dict(session=session,received_ms=now,message=message)
                    sample=sampler.ingest(row)
                    topic=message.get('topic','');symbol=topic.split('.')[-1]
                    if topic.startswith('orderbook.') and symbol in sampler.books:
                        b=sampler.books[symbol]
                        if b['received_ms']==now and now-last_book.get(symbol,0)>=200:
                            last_book[symbol]=now
                            quote=dict(symbol=symbol,ts=now,event_ms=int(message['ts']),session=session,
                                bids=sorted(b['b'].items(),reverse=True)[:50],asks=sorted(b['a'].items())[:50])
                            for k,db in accounts.items():
                                state=states[k]
                                if (state['position'] and state['position']['symbol']==symbol) or state['pending']:
                                    db.apply(f'book:{session}:{symbol}:{b["u"]}',dict(type='book',row=quote,
                                        paused=is_paused or closing),{symbol:inst[symbol]})
                                    states[k]=db.state()
                    if sample:
                        last_sample_ms=now
                        for k in accounts:cache[k][symbol]=signals(sample,k)
                        if now>=next_decision and decision_due is None:
                            decision_due=now+500  # Causal gather window; no future sample is included.
                    if decision_due is not None and now>=decision_due and not closing:
                        for k,db in accounts.items():
                            options=[item for values in cache[k].values() for item in values]
                            event=dict(type='decision',now_ms=now,signals=options,paused=is_paused)
                            db.apply(f'decision:{session}:{now}',event);states[k]=db.state()
                        next_decision=now+4500;decision_due=None
                    if mono-last_status>=5:
                        atomic_json(directory/'status.json',dict(updated_ms=now,pid=os.getpid(),
                            protocol_sha256=identity,session=session,received_messages=received_messages,
                            paused=is_paused,failures=failures,ready=False,candidate='CASH',
                            mode=protocol['mode'],accounts=states,sampler_audit=dict(sampler.audit),
                            last_sample_ms=last_sample_ms,valid_books=sorted(sampler.books)))
                        last_status=mono
                    if now-inst_ms>=3600000 and all(not s['position'] and not s['pending'] for s in states.values()):
                        break  # Refresh public lot rules with all accounts flat, then warm a new stream.
            except (OSError,ValueError,RuntimeError,KeyError,websocket.WebSocketException) as exc:
                failures+=1
                atomic_json(directory/'connection-error.json',dict(updated_ms=time.time_ns()//1000000,
                    error=type(exc).__name__,reason=str(exc)[:250],ready=False))
                # Existing positions remain durable and are managed on the next valid snapshot.
                time.sleep(min(30,2*failures))
            finally:
                if ws:ws.close()
    finally:
        atomic_json(directory/'status.json',dict(updated_ms=time.time_ns()//1000000,
            pid=os.getpid(),stage='stopped',protocol_sha256=identity,ready=False,
            candidate='CASH',received_messages=received_messages,failures=failures,accounts=states))
        for db in accounts.values():db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--duration',type=int)
    args=p.parse_args();run(args.directory,args.duration)
