"""Durable public point-in-time channels; isolated from the existing bounded recorder."""
import argparse, fcntl, gzip, json, os, pathlib, shutil, time, uuid
import websocket
from brain_research import ROOT, SYMBOLS, write
LIMIT=4*1024**3  # daily raw compressed budget, with explicit gap reporting
def run(directory,once=False):
    directory.mkdir(parents=True,exist_ok=True)
    lock=(ROOT/"data/brain-channels.lock").open("a");fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    for key in list(os.environ):
        if "proxy" in key.lower():del os.environ[key]
    while True:
        ws=None
        session=uuid.uuid4().hex
        started=time.time();day=time.strftime("%Y%m%d",time.gmtime());folder=directory/day
        folder.mkdir(exist_ok=True)
        try:
            total=sum(p.stat().st_size for p in folder.glob("*"))
            all_bytes=sum(p.stat().st_size for p in directory.glob("*/*.jsonl.gz"))
            if all_bytes>=60*1024**3 or total>=LIMIT or shutil.disk_usage(directory).free<10*1024**3:
                raise RuntimeError("storage budget reached; explicit collection gap")
            ws=websocket.create_connection("wss://stream.bybit.com/v5/public/linear",timeout=10)
            topics=[f"{kind}.{s}" for s in SYMBOLS for kind in
                    ("orderbook.50","publicTrade","tickers","allLiquidation","kline.15")]
            for i in range(0,len(topics),10):ws.send(json.dumps(dict(op="subscribe",args=topics[i:i+10])))
            path=folder/(str(int(started*1000))+"-"+session[:8]+".jsonl.gz")
            counts={};last_ping=started;last_flush=started
            with gzip.open(path,"wt",compresslevel=3) as f:
                f.write(json.dumps(dict(session=session,event="connect",received_ms=int(time.time()*1000),
                                        monotonic_ns=time.monotonic_ns(),symbols=SYMBOLS))+"\n")
                while time.time()-started<300:
                    try:raw=ws.recv()
                    except websocket.WebSocketTimeoutException:
                        ws.send(json.dumps(dict(op="ping")));continue
                    if not raw:raise RuntimeError("closed stream")
                    received=time.time_ns()//1000000;mono=time.monotonic_ns();message=json.loads(raw)
                    if message.get("success") is False:raise RuntimeError("subscription rejected")
                    topic=message.get("topic","control");counts[topic]=counts.get(topic,0)+1
                    f.write(json.dumps(dict(session=session,received_ms=received,monotonic_ns=mono,
                                            message=message),separators=(",",":"))+"\n")
                    now=time.time()
                    if now-last_ping>=20:ws.send(json.dumps(dict(op="ping")));last_ping=now
                    if now-last_flush>=5:
                        f.flush();last_flush=now
                        write(directory/"status.json",dict(session=session,updated_ms=received,stage="recording",
                              counts=counts,path=str(path),bytes_today=total+path.stat().st_size,
                              limitations="Raw snapshots/deltas retained; no validated microstructure alpha yet"))
                        if total+path.stat().st_size>=LIMIT:raise RuntimeError("daily storage budget")
                    if once and sum(counts.values())>=10:break
                f.write(json.dumps(dict(session=session,event="disconnect",received_ms=int(time.time()*1000)))+"\n")
            if once:return
        except Exception as exc:
            write(directory/"status.json",dict(stage="gap",updated_ms=int(time.time()*1000),
                  session=session,error=type(exc).__name__,reason=str(exc)[:160]))
            with (directory/"gaps.jsonl").open("a") as f:
                f.write(json.dumps(dict(session=session,ms=int(time.time()*1000),reason=str(exc)[:160]))+"\n")
            if once:raise
            time.sleep(30)
        finally:
            if ws:ws.close()
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--directory",type=pathlib.Path,required=True)
    p.add_argument("--once",action="store_true");a=p.parse_args();run(a.directory,a.once)
