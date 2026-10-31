"""Finite public-stream/slow-ledger audit. Synthetic CASH accounts only."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import time
import uuid
import numpy as np
import websocket
from brain_impulse_transport import BufferedReceiver,fresh_for_decision
from brain_impulse_data import ImpulseSampler,atomic_json
from brain_impulse_execution import DurablePaper
from brain_archive_stream import sha


def run(directory,duration=120):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    with (directory/'audit.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (directory/'identity.json').exists():raise ValueError('Preserve prior audit; use a new directory')
        session=uuid.uuid4().hex
        atomic_json(directory/'identity.json',dict(session=session,duration_s=duration,synthetic_stall_s=4.5,
            source={n:sha(Path(__file__).parent/n) for n in ('brain_impulse_transport.py','brain_impulse_transport_audit.py','brain_impulse_data.py','brain_impulse_execution.py')},ready=False))
        for key in list(os.environ):
            if 'proxy' in key.lower():del os.environ[key]
        accounts=[DurablePaper(directory/f'cash-{i}.sqlite3',protocol_id='transport-audit:'+session) for i in range(3)]
        receiver=None;ws=None;completed=False;failure=None;sampler=ImpulseSampler()
        reads=0;samples=0;stale_samples=0;decisions=0;stalled=False;queue_ages=[];book_lags=[];write_times=[]
        started=time.monotonic();next_write=started+65
        try:
            ws=websocket.create_connection('wss://stream.bybit.com/v5/public/linear',timeout=5)
            topics=[f'{kind}.{s}' for s in ('BTCUSDT','ETHUSDT','SOLUSDT','DOGEUSDT','XRPUSDT','BNBUSDT')
                    for kind in ('orderbook.50','publicTrade','tickers','allLiquidation')]
            for i in range(0,len(topics),10):ws.send(json.dumps(dict(op='subscribe',args=topics[i:i+10])))
            receiver=BufferedReceiver(ws,session).start()
            while time.monotonic()-started<duration:
                if not stalled and time.monotonic()-started>=70:
                    time.sleep(4.5);stalled=True  # Deliberately block only the consumer.
                try:row=receiver.get(timeout=1)
                except TimeoutError:continue
                reads+=1;now=time.time_ns()//1000000;mono=time.monotonic_ns()
                queue_ages.append((mono-row['received_monotonic_ns'])/1000000)
                if row['message'].get('topic','').startswith('orderbook.'):
                    book_lags.append(row['received_ms']-int(row['message']['ts']))
                sample=sampler.ingest(row)
                if sample:
                    samples+=1
                    if not fresh_for_decision(row,now,mono):stale_samples+=1;continue
                    if time.monotonic()>=next_write:
                        begin=time.monotonic()
                        # Recheck clock for EACH account after any preceding slow commit.
                        for i,db in enumerate(accounts):
                            if not fresh_for_decision(row):break
                            db.apply(f'{session}:{reads}:{i}',dict(type='decision',now_ms=time.time_ns()//1000000,signals=[]))
                            decisions+=1
                        write_times.append((time.monotonic()-begin)*1000);next_write=time.monotonic()+5
            completed=True
        except Exception as exc:
            failure=type(exc).__name__+': '+str(exc)[:200]
            raise
        finally:
            if receiver:receiver.close()
            elif ws:ws.close()
            states=[db.state() for db in accounts]
            for db in accounts:db.close()
            def quantiles(values):
                return dict(zip(('p50','p95','p99','max'),map(float,np.quantile(values,[.5,.95,.99,1])))) if values else {}
            atomic_json(directory/'result.json',dict(completed=completed,error=failure,duration_s=time.monotonic()-started,
                reads=reads,samples=samples,stale_samples_rejected=stale_samples,cash_decisions=decisions,
                synthetic_stall_applied=stalled,queue_age_ms=quantiles(queue_ages),book_receive_lag_ms=quantiles(book_lags),
                write_ms=quantiles(write_times),transport=receiver.metrics() if receiver else {},
                sampler_audit=dict(sampler.audit),accounts=states,ready=False,financial_evidence=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--duration',type=int,default=120);a=p.parse_args();run(a.directory,a.duration)
