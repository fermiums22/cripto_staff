"""Versioned buffered PAPER control audit. Candidate remains CASH.

Receipt time drives features; actual processing time drives decisions/fills.
Original receipt/event timestamps are retained in each executed book journal.
No model promotion, private endpoint, or existing-wallet migration is supported.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import time
import uuid
import websocket
from brain_archive_stream import sha
from brain_impulse_data import ImpulseSampler,atomic_json
from brain_impulse_transport import BufferedReceiver,fresh_for_decision
from brain_impulse_execution import DurablePaper,ExecutionPolicy,policy_digest
from brain_impulse_controls import signals
from brain_impulse_live import instruments,paused,SYMBOLS,ROOT

FILES=('brain_impulse_buffered_live.py','brain_impulse_transport.py','brain_impulse_data.py',
       'brain_impulse_execution.py','brain_impulse_controls.py','brain_impulse_live.py')
CONTROLS=('cash','momentum','leadlag_flow')


def quote_for_execution(raw,sampler,now_ms,now_mono,pending=None):
    if not fresh_for_decision(raw,now_ms,now_mono):return None
    if pending and raw['received_ms']<pending['eligible_ms']:return None
    message=raw['message'];topic=message.get('topic','')
    if not topic.startswith('orderbook.'):return None
    symbol=topic.split('.')[-1];book=sampler.books.get(symbol)
    if book is None or book['received_ms']!=raw['received_ms']:return None
    return dict(symbol=symbol,session=raw['session'],ts=now_ms,event_ms=int(message['ts']),
        source_received_ms=raw['received_ms'],processing_delay_ms=(now_mono-raw['received_monotonic_ns'])/1000000,
        receive_sequence=raw['receive_sequence'],bids=sorted(book['b'].items(),reverse=True)[:50],
        asks=sorted(book['a'].items())[:50])


def prepare(directory):
    directory.mkdir(parents=True,exist_ok=True);path=directory/'protocol.json'
    identity=dict(source={n:sha(ROOT/n) for n in FILES},policy_sha256=policy_digest(ExecutionPolicy()),
        controls=list(CONTROLS),candidate='CASH',ready=False,
        mode='buffered_control_execution_audit',receipt_clock='receiver wall and monotonic',
        execution_clock='actual processing wall time, original receipt retained',
        min_book_interval_ms=200,decision_gather_ms=500)
    if path.exists() and json.loads(path.read_text())!=identity:raise ValueError('Frozen buffered trial changed')
    if not path.exists():atomic_json(path,identity)
    snapshot=directory/'source';snapshot.mkdir(exist_ok=True)
    for name,h in identity['source'].items():
        target=snapshot/name
        if not target.exists():target.write_bytes((ROOT/name).read_bytes())
        if sha(target)!=h:raise ValueError('Source snapshot changed')
    return sha(path)


def run(directory,duration=180):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    with (directory/'worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        identity=prepare(directory)
        accounts={k:DurablePaper(directory/(k+'.sqlite3'),protocol_id=identity+':'+k) for k in CONTROLS}
        states={k:db.state() for k,db in accounts.items()}
        for key in list(os.environ):
            if 'proxy' in key.lower():del os.environ[key]
        started=time.monotonic();end=started+duration;closing=False;failures=0;processed=0;stale=0;samples=0
        receiver=None;transport={};last_status=0.;session=None
        try:
            while time.monotonic()<end+60:
                ws=None
                try:
                    inst=instruments();inst_ms=time.time_ns()//1000000
                    atomic_json(directory/f'instruments-{inst_ms}.json',dict(received_ms=inst_ms,instruments=inst))
                    session=uuid.uuid4().hex;sampler=ImpulseSampler();cache={k:{} for k in CONTROLS}
                    last_book={};due=None;next_decision=0;pause_at=0;is_paused=True
                    last_sample=None;connected=time.time_ns()//1000000
                    ws=websocket.create_connection('wss://stream.bybit.com/v5/public/linear',timeout=5)
                    topics=[f'{kind}.{s}' for s in SYMBOLS for kind in ('orderbook.50','publicTrade','tickers','allLiquidation')]
                    for i in range(0,len(topics),10):ws.send(json.dumps(dict(op='subscribe',args=topics[i:i+10])))
                    receiver=BufferedReceiver(ws,session).start()
                    while time.monotonic()<end+60:
                        mono=time.monotonic();now=time.time_ns()//1000000
                        if mono>=end and not closing:
                            closing=True
                            for k,db in accounts.items():
                                db.apply('finite-end:'+identity,dict(type='halt',reason='finite_buffered_audit_end'));states[k]=db.state()
                        if closing and all(not s['position'] and not s['pending'] for s in states.values()):return
                        if mono-pause_at>=1:is_paused=paused(ROOT/'data/agent.sqlite3');pause_at=time.monotonic()
                        try:raw=receiver.get(timeout=1)
                        except TimeoutError:continue
                        processed+=1;sample=sampler.ingest(raw)
                        now=time.time_ns()//1000000;fresh=fresh_for_decision(raw,now,time.monotonic_ns())
                        if not fresh:stale+=1
                        if sample:
                            samples+=1;last_sample=sample['ts']
                            for k in CONTROLS:cache[k][sample['symbol']]=(raw,signals(sample,k))
                            if fresh and now>=next_decision and due is None:due=now+500
                        symbol=raw['message'].get('topic','').split('.')[-1]
                        if fresh and raw['message'].get('topic','').startswith('orderbook.') and now-last_book.get(symbol,0)>=200:
                            last_book[symbol]=now
                            for k,db in accounts.items():
                                state=states[k]
                                if not (state['pending'] or (state['position'] and state['position']['symbol']==symbol)):continue
                                quote=quote_for_execution(raw,sampler,time.time_ns()//1000000,time.monotonic_ns(),state['pending'])
                                if quote is None:continue
                                db.apply(f'book:{session}:{raw["receive_sequence"]}',dict(type='book',row=quote,
                                    paused=is_paused or closing),{symbol:inst[symbol]});states[k]=db.state()
                        now=time.time_ns()//1000000
                        if due is not None and now>=due and not closing:
                            for k,db in accounts.items():
                                # Current clock re-evaluated after every durable write.
                                decision_now=time.time_ns()//1000000
                                decision_mono=time.monotonic_ns()
                                options=[s for origin,values in cache[k].values()
                                         if fresh_for_decision(origin,decision_now,decision_mono) for s in values]
                                db.apply(f'decision:{session}:{decision_now}:{raw["receive_sequence"]}',
                                    dict(type='decision',now_ms=decision_now,signals=options,paused=is_paused))
                                states[k]=db.state()
                            next_decision=time.time_ns()//1000000+4500;due=None
                        if time.monotonic()-last_status>=5:
                            transport=receiver.metrics()
                            atomic_json(directory/'status.json',dict(stage='running',pid=os.getpid(),updated_ms=time.time_ns()//1000000,
                                protocol_sha256=identity,session=session,processed=processed,samples=samples,
                                stale_rows=stale,transport=transport,failures=failures,accounts=states,candidate='CASH',ready=False))
                            last_status=time.monotonic()
                        # Evaluate continuity only after queued rows have been reconstructed.
                        if receiver.metrics()['queued']==0:
                            if now-connected>65000 and any(s not in sampler.books for s in ('BTCUSDT','ETHUSDT')):
                                raise RuntimeError('Leader snapshot required')
                            if last_sample is not None and now-last_sample>20000:raise RuntimeError('Feature continuity lost')
                except (OSError,ValueError,RuntimeError,KeyError,websocket.WebSocketException) as exc:
                    failures+=1
                    atomic_json(directory/'connection-error.json',dict(error=type(exc).__name__,reason=str(exc)[:200],ready=False))
                    if time.monotonic()<end:time.sleep(min(5,failures))
                finally:
                    if receiver:transport=receiver.metrics();receiver.close();receiver=None
                    elif ws:ws.close()
        finally:
            atomic_json(directory/'status.json',dict(stage='stopped',pid=os.getpid(),updated_ms=time.time_ns()//1000000,
                protocol_sha256=identity,processed=processed,samples=samples,stale_rows=stale,transport=transport,
                failures=failures,accounts=states,candidate='CASH',ready=False,
                unresolved_positions=any(s['position'] or s['pending'] for s in states.values())))
            for db in accounts.values():db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--duration',type=int,default=180);a=p.parse_args();run(a.directory,a.duration)
