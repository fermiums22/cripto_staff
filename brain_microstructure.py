"""Alternative architecture: receive-time order-flow samples and daily GPU research.
No promotion, no private endpoints. Diagnostic rejection before a new prospective trial.
"""
import argparse, collections, fcntl, gzip, json, pathlib, time
import numpy as np
from brain_research import Net, FEE, SLIP, fit_scaler, transform, write
import torch

class Sampler:
    def __init__(self):
        self.books={};self.prices=collections.defaultdict(collections.deque)
        self.flows=collections.defaultdict(collections.deque)
        self.last={};self.session=None
    def ingest(self,row):
        if row.get("session")!=self.session:
            self.__init__();self.session=row.get("session")
        m=row.get("message",{});topic=m.get("topic","");stamp=row.get("received_ms",0)
        if topic.startswith("publicTrade."):
            symbol=topic.split(".")[-1]
            for t in m["data"]:
                self.flows[symbol].append((stamp,float(t["v"])*(1 if t["S"]=="Buy" else -1)))
            while self.flows[symbol] and stamp-self.flows[symbol][0][0]>30000:self.flows[symbol].popleft()
            return None
        if not topic.startswith("orderbook."):return None
        symbol=topic.split(".")[-1];d=m["data"];event=int(m["ts"])
        if not 0<=stamp-event<=1500:
            # A skipped delta makes the local book incomplete until a new snapshot.
            self.books.pop(symbol,None)
            self.prices.pop(symbol,None)
            return None
        reset=m.get("type")=="snapshot" or d.get("u")==1
        if reset:self.books[symbol]={"b":{},"a":{},"seq":-1,"ms":stamp}
        if symbol not in self.books:return None
        b=self.books[symbol]
        if int(d.get("seq",0))<b["seq"] and not reset:
            self.books.pop(symbol);self.prices.pop(symbol,None);return None
        for side in ("b","a"):
            for p,q in d.get(side,[]):
                p,q=float(p),float(q)
                if not np.isfinite(p*q) or p<=0 or q<0:raise ValueError("invalid book level")
                if q==0:b[side].pop(p,None)
                else:b[side][p]=q
        b.update(seq=int(d.get("seq",0)),ms=stamp)
        if not b["b"] or not b["a"]:return None
        bid=max(b["b"]);ask=min(b["a"])
        if bid>=ask:self.books.pop(symbol);self.prices.pop(symbol,None);return None
        mid=(bid+ask)/2
        prices=self.prices[symbol]
        if not prices or stamp-prices[-1][0]>=1000:prices.append((stamp,mid))
        while prices and stamp-prices[0][0]>125000:prices.popleft()
        if stamp-self.last.get(symbol,0)<5000:return None
        def ret(s,lag):
            h=self.prices[s]
            if not h or stamp-h[-1][0]>1500:return None
            prior=next((p for t,p in reversed(h) if t<=stamp-lag),None)
            return None if prior is None else np.log(h[-1][1]/prior)
        returns=[ret(symbol,30000),ret(symbol,120000),ret("BTCUSDT",30000),ret("ETHUSDT",30000)]
        if any(v is None for v in returns):return None
        bv=sum(p*b["b"][p] for p in sorted(b["b"],reverse=True)[:10])
        av=sum(p*b["a"][p] for p in sorted(b["a"])[:10])
        flow=[q for t,q in self.flows[symbol] if stamp-t<=30000]
        ratio=sum(flow)/(sum(abs(q) for q in flow)+1e-12)
        x=[(bv-av)/(bv+av),(ask-bid)/mid,*returns,ratio,np.log1p(min(bv,av))]
        self.last[symbol]=stamp
        return dict(symbol=symbol,received_ms=stamp,event_ms=event,x=x,bid=bid,ask=ask,
                    bid_depth=bv,ask_depth=av,session=self.session)

def extract(directory):
    out=directory/"samples-v2";out.mkdir(exist_ok=True)
    files=sorted(p for p in directory.glob("*/*.jsonl.gz") if p.parent.name not in ("samples", "samples-v2"))
    count=0
    for source in files:
        dest=out/(source.stem+".samples.npz")
        if dest.exists() or time.time()-source.stat().st_mtime<310:continue
        sampler=Sampler();rows=[]
        try:
            with gzip.open(source,"rt") as f:
                for line in f:
                    sample=sampler.ingest(json.loads(line))
                    if sample:rows.append(sample)
        except (EOFError,OSError,json.JSONDecodeError):continue
        np.savez_compressed(dest,ts=np.array([r["received_ms"] for r in rows],dtype="int64"),
            symbols=np.array([r["symbol"] for r in rows]),x=np.array([r["x"] for r in rows]),
            bid=np.array([r["bid"] for r in rows]),ask=np.array([r["ask"] for r in rows]),
            depth=np.array([min(r["bid_depth"],r["ask_depth"]) for r in rows]),
            sessions=np.array([r["session"] for r in rows]))
        count+=len(rows)
    return count

def research(directory):
    lock=(directory/"micro.lock").open("a");fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    extract(directory)
    loaded=[np.load(p) for p in sorted((directory/"samples-v2").glob("*.npz"))]
    loaded=[d for d in loaded if len(d["ts"])]
    status=directory/"micro_research.json"
    if not loaded:
        write(status,dict(stage="collecting",ready=False,reason="No matured continuous samples"));return
    d={k:np.concatenate([v[k] for v in loaded]) for k in loaded[0].files}
    order=np.argsort(d["ts"]);d={k:v[order] for k,v in d.items()}
    from brain_micro_prospective import evaluate_due, reserve
    from brain_micro_validation import compare
    evaluate_due(directory, d)
    # Reserved prospective observations must never enter development selection.
    for protocol_path in (directory/"prospective-v1").glob("*/protocol.json"):
        protocol=json.loads(protocol_path.read_text())
        keep=(d["ts"] < protocol["future_start_ms"]) | (d["ts"] >= protocol["future_end_ms"])
        d={k:v[keep] for k,v in d.items()}
    if not len(d["ts"]):return
    span=int(d["ts"][-1]-d["ts"][0])
    hours,counts=np.unique(d["ts"]//3600000,return_counts=True)
    days,active_hours=np.unique(hours[counts>=100]//24,return_counts=True)
    qualified_days=int((active_hours>=20).sum())
    if span<7*86400000 or qualified_days<7:
        write(status,dict(stage="collecting",samples=len(order),span_days=span/86400000,
              required_days=7,qualified_days=qualified_days,ready=False,reason="Need seven days with at least 20 covered hours; do not fit yet"));return
    from brain_micro_validation import labelled_samples
    x,y,ts = labelled_samples(d, FEE, SLIP)
    if len(ts)<1000:
        write(status,dict(stage="collecting",ready=False,samples=len(ts),
                         reason="Too few continuous same-session labelled samples"));return
    cut=ts[int(len(ts)*.7)];train=np.where(ts<cut-180000)[0];val=np.where(ts>cut+180000)[0]
    mean=x[train].mean(0);std=np.maximum(x[train].std(0),1e-6);z=transform(x,mean,std)
    device="cuda"
    if not torch.cuda.is_available():raise RuntimeError("GPU required")
    torch.manual_seed(19);net=Net().to(device);opt=torch.optim.AdamW(net.parameters(),lr=.001)
    tx=torch.from_numpy(z[train]).to(device);ty=torch.from_numpy(y[train]*100).to(device)
    for epoch in range(20):
        import ctypes
        nv=ctypes.CDLL("/opt/nvidia-driver/libnvidia-ml.so.1")
        if nv.nvmlInit_v2()!=0:raise RuntimeError("GPU thermal telemetry unavailable")
        handle=ctypes.c_void_p();temp=ctypes.c_uint()
        if nv.nvmlDeviceGetHandleByIndex_v2(0,ctypes.byref(handle))!=0:raise RuntimeError("GPU handle unavailable")
        if nv.nvmlDeviceGetTemperature(handle,0,ctypes.byref(temp))!=0 or temp.value>=82:raise RuntimeError("GPU temperature guard")
        for b in torch.randperm(len(tx),device=device).split(2048):
            opt.zero_grad(set_to_none=True);loss=(net(tx[b])-ty[b]).square().mean()
            if not torch.isfinite(loss):raise RuntimeError("Nonfinite micro training loss")
            loss.backward();torch.nn.utils.clip_grad_norm_(net.parameters(),1.);opt.step()
    net.eval()
    with torch.no_grad():pred=net(torch.from_numpy(z[val]).to(device)).cpu().numpy()/100
    report=compare(pred,x[val],y[val],ts[val])
    stamp=str(int(time.time()))
    model=directory/("micro-"+stamp+".pt")
    scaler=directory/("micro-"+stamp+"-scaler.npz")
    torch.save(net.state_dict(),model)
    np.savez_compressed(scaler,mean=mean,std=std)
    trial=reserve(directory,model,scaler,report)
    result=dict(stage="research_only",ready=False,samples=len(ts),span_days=span/86400000,
        gpu=torch.cuda.get_device_name(),comparison=report,prospective_trial=trial,
        reason="Development results only; prospective replay and full-depth live PAPER required")
    write(directory/("micro-"+stamp+"-report.json"),result)
    write(status,result)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--directory",type=pathlib.Path,required=True)
    research(p.parse_args().directory)
