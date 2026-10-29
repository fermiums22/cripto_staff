"""Public raw WebSocket recorder, bounded disk use, no trading credentials."""
import gzip
import json
import os
import shutil
import time
import uuid
import websocket
import agent
from portfolio_market import scan,write


def run():
    for key in list(os.environ):
        if 'proxy' in key.lower():del os.environ[key]
    directory=agent.DATA/'market_stream';directory.mkdir(parents=True,exist_ok=True)
    while True:
        ws=None
        try:
            report,_=scan();symbols=report.get('watchlist',report['shortlist'][:5])
            if not symbols:raise RuntimeError('No eligible instruments')
            session=uuid.uuid4().hex;counts={};started=time.time();ping=started;health=0.
            ws=websocket.create_connection('wss://stream.bybit.com/v5/public/linear',timeout=30)
            topics=[f'{prefix}.{s}' for s in symbols for prefix in ('orderbook.50','publicTrade','tickers','allLiquidation')]
            ws.send(json.dumps(dict(op='subscribe',args=topics)))
            filename=directory/(time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+session[:8]+'.jsonl.gz')
            # New sessions every five minutes: snapshots anchor deltas; reconnect gaps
            # remain visible through session IDs and receive timestamps.
            with gzip.open(filename,'at',compresslevel=3) as f:
                f.write(json.dumps(dict(session=session,event='connect',received_ms=int(time.time()*1000),symbols=symbols))+'\n')
                while time.time()-started<300:
                    raw=ws.recv()
                    if not raw:raise ConnectionError('Closed stream')
                    message=json.loads(raw);now=time.time()
                    if message.get('success') is False:raise RuntimeError('Subscription rejected')
                    topic=message.get('topic','control');counts[topic]=counts.get(topic,0)+1
                    f.write(json.dumps(dict(session=session,received_ms=int(now*1000),message=message))+'\n')
                    if now-ping>20:ws.send(json.dumps(dict(op='ping')));ping=now
                    if now-health>10:
                        f.flush();files=sorted(directory.glob('*.jsonl.gz'),key=lambda p:p.stat().st_mtime)
                        total=sum(p.stat().st_size for p in files)
                        for old in files:
                            if total<=200*1024**2:break
                            if old==filename:continue
                            size=old.stat().st_size;old.unlink();total-=size
                        if total>220*1024**2 or shutil.disk_usage(directory).free<512*1024**2:
                            raise RuntimeError('Recorder storage budget reached')
                        write(agent.ARTIFACTS/'market_stream_status.json',dict(stage='recording',session=session,
                            symbols=symbols,counts=counts,updated_ms=int(now*1000),bytes=total))
                        health=now
        except Exception as exc:
            write(agent.ARTIFACTS/'market_stream_status.json',dict(stage='reconnecting',error=type(exc).__name__,updated_ms=int(time.time()*1000)))
            time.sleep(10)
        finally:
            if ws is not None:ws.close()


if __name__=='__main__':run()
