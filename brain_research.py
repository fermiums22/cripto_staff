"""Isolated Market Brain experiments. All old history is development, never pristine test."""
import argparse, gzip, hashlib, json, os, pathlib, time
os.environ.setdefault("OMP_NUM_THREADS", "2")
import numpy as np
import torch
from torch import nn

ROOT = pathlib.Path(__file__).resolve().parent
STORE = pathlib.Path("/home/codex/projects/market-brain-storage/evidence-v1")
STEP = 900000
FEE = .0006  # conservative scenario, NOT authenticated personal fee
SLIP = .0003
HISTORY_COST = 2 * (FEE + SLIP) + .0004
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT", "BNBUSDT"]
torch.set_num_threads(2)

def write(path, value):
    path = pathlib.Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(value, f, allow_nan=False, sort_keys=True, indent=2)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

def digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()

def features(a):
    """Only trailing rows; no fitted/global statistics in feature calculation."""
    a = np.asarray(a, dtype=np.float64)
    if not np.isfinite(a).all() or (a[:,:,1:5] <= 0).any():
        raise ValueError("bad candles")
    c = a[:,:,4]
    r = np.zeros_like(c)
    r[1:] = np.log(c[1:] / c[:-1])
    lag = lambda n: np.concatenate([np.zeros_like(c[:n]), np.log(c[n:]/c[:-n])])
    v = np.log1p(a[:,:,5])
    vd = np.zeros_like(v); vd[1:] = v[1:] - v[:-1]
    btc = np.broadcast_to(r[:,0:1], r.shape)
    eth = np.broadcast_to(r[:,1:2], r.shape)
    return np.stack([r,lag(4),lag(16),np.log(a[:,:,2]/a[:,:,3]),
                     np.log(c/a[:,:,1]),vd,btc,eth], axis=-1).astype("float32")

def fit_scaler(x):
    return x.mean(axis=(0,1)), np.maximum(x.std(axis=(0,1)), 1e-6)

def transform(x, mean, std):
    return np.clip((x-mean)/std, -10, 10).astype("float32")

def load_data():
    data = {}; hashes = {}; metadata = {}
    for symbol in SYMBOLS:
        p = ROOT/"data"/"portfolio"/(symbol+".json.gz")
        d = json.load(gzip.open(p))
        rows = np.asarray(sorted(d["trade"]), dtype="float64")
        if len(set(rows[:,0])) != len(rows):
            raise ValueError("duplicate candle")
        data[symbol] = {int(r[0]):r[:6] for r in rows}
        hashes[symbol] = digest(p)
        metadata[symbol] = dict(instrument=d["instrument"], funding=d["funding"])
    ts = np.asarray(sorted(set.intersection(*(set(d) for d in data.values()))))
    if len(ts)<1000 or np.any(np.diff(ts)!=STEP):
        raise ValueError("missing aligned history")
    a = np.stack([[data[s][int(t)] for s in SYMBOLS] for t in ts])
    return ts, a, hashes, metadata

class Net(nn.Module):
    def __init__(self, width=32):
        super().__init__()
        self.layers = nn.Sequential(nn.Linear(8,width),nn.SiLU(),
                                    nn.Linear(width,width),nn.SiLU(),nn.Linear(width,1))
    def forward(self,x):
        return self.layers(x).squeeze(-1)

def pnl_series(pred, a, ts, metadata, threshold, cost=HISTORY_COST):
    """Long/short, one position, 1x, next open to following open; diagnostic proxy."""
    idx = np.argmax(np.abs(pred),axis=1)
    side = np.sign(pred[np.arange(len(pred)),idx])
    active = np.abs(pred[np.arange(len(pred)),idx]) > threshold
    gross = (a[2:, :,1]/a[1:-1,:,1]-1)[np.arange(len(pred)),idx]*side
    funding = np.zeros(len(pred))
    for j,s in enumerate(SYMBOLS):
        for row in metadata[s]["funding"]:
            stamp = int(row["fundingRateTimestamp"])
            k = np.searchsorted(ts,stamp,side="right")-2
            if 0<=k<len(pred) and idx[k]==j:
                funding[k] += side[k]*float(row["fundingRate"])
    return np.where(active, gross-cost-funding, 0.), active

def metrics(pnl, active, ts):
    equity = np.cumprod(1+np.clip(pnl,-.99,10))
    peak = np.maximum.accumulate(np.r_[1.,equity])[1:]
    days = ts//86400000
    daily = np.array([pnl[days==d].sum() for d in np.unique(days)])
    rng = np.random.default_rng(812)
    boot = rng.choice(daily,(2000,len(daily)),replace=True).mean(axis=1) if len(daily) else [0]
    return dict(net_return=float(equity[-1]-1), max_drawdown=float(np.max(1-equity/peak)),
                trades=int(active.sum()), mean_daily_lower95=float(np.quantile(boot,.025)),
                days=len(daily), costs_are_assumptions=True)

def train(run):
    run.mkdir(parents=True, exist_ok=False)
    ts,a,hashes,meta = load_data()
    x = features(a)[:-2]
    y = (a[2:,:,1]/a[1:-1,:,1]-1).astype("float32")
    n=len(x); cut=int(n*.65); end=int(n*.85)
    # Targets end at i+2. Purge them plus a full feature window at each boundary.
    tr=np.arange(32,cut-18); va=np.arange(cut+16,end-2); audit=np.arange(end+16,n)
    mean,std=fit_scaler(x[tr]); z=transform(x,mean,std)
    protocol=dict(version=1,created_ms=int(time.time()*1000),symbols=SYMBOLS,
      source_hashes=hashes,history_last_ms=int(ts[-1]),train_last_ms=int(ts[tr[-1]+2]),
      validation_start_ms=int(ts[va[0]]),validation_end_ms=int(ts[va[-1]+2]),
      diagnostic_start_ms=int(ts[audit[0]]),historical_test_is_pristine=False,
      fee_per_side=FEE,slippage_per_side=SLIP,history_extra_spread=.0004,
      future_days=14,minimum_closed_trades=100,minimum_symbols=3,max_drawdown=.10,
      latency_ms=1000,max_quote_age_ms=1500,model_freeze_after_selection=True,
      ready=False,ready_reason="future PAPER not completed",
      source_code_sha256={p:digest(ROOT/p) for p in ["brain_research.py","brain_forward.py","motivation_core.py"]})
    write(run/"protocol.json",protocol)  # before fitting/selection
    np.savez(run/"scaler.npz",mean=mean,std=std)
    predictions={"zero":np.zeros_like(y),"momentum":x[:,:,0],"reversal":-x[:,:,0]}
    tx=torch.from_numpy(z[tr].reshape(-1,8)); ty=torch.from_numpy(y[tr].reshape(-1)*100)
    design=np.c_[tx.numpy(),np.ones(len(tx))]
    ridge=np.linalg.solve(design.T@design+100*np.eye(9),design.T@ty.numpy())/100
    np.save(run/"ridge.npy",ridge)
    predictions["ridge"]=np.einsum("tad,d->ta",z,ridge[:8])+ridge[8]
    if not torch.cuda.is_available():raise RuntimeError("RTX training required; CUDA unavailable")
    device="cuda";tx=tx.to(device);ty=ty.to(device)
    gpu=dict(name=torch.cuda.get_device_name(),torch=torch.__version__,cuda=torch.version.cuda)
    for seed in (17,53):
        torch.manual_seed(seed);net=Net().to(device);opt=torch.optim.AdamW(net.parameters(),lr=.001)
        best=float("inf");stall=0;checkpoint=None
        vx=torch.from_numpy(z[va]).to(device);vy=torch.from_numpy(y[va]*100).to(device)
        for epoch in range(100):
            net.train()
            order=torch.randperm(len(tx),device=device)
            for batch in order.split(2048):
                opt.zero_grad(set_to_none=True)
                loss=(net(tx[batch])-ty[batch]).square().mean()
                if not torch.isfinite(loss):raise ValueError("nonfinite training loss")
                loss.backward();nn.utils.clip_grad_norm_(net.parameters(),1.);opt.step()
            net.eval()
            with torch.no_grad():v=float((net(vx)-vy).square().mean())
            if v < best-1e-7:
                best=v;stall=0;checkpoint={k:t.detach().cpu().clone() for k,t in net.state_dict().items()}
            else:stall+=1
            write(run/("training-"+str(seed)+".json"),dict(epoch=epoch,val_mse=v,best=best,gpu=gpu))
            if stall>=10:break
        net.load_state_dict(checkpoint)
        torch.save(checkpoint,run/("mlp-"+str(seed)+".pt"))
        with torch.no_grad():
            predictions["mlp-"+str(seed)]=net(torch.from_numpy(z).to(device)).cpu().numpy()/100
    candidates=[]
    for name,pred in predictions.items():
        for threshold in ([1.] if name=="zero" else [.0022,.004,.008]):
            series,active=pnl_series(pred,a,ts,meta,threshold)
            stress,_=pnl_series(pred,a,ts,meta,threshold,HISTORY_COST*2)
            val=metrics(series[va],active[va],ts[va])
            candidates.append(dict(name=name,threshold=threshold,validation=val,
                                   stress_validation=metrics(stress[va],active[va],ts[va])))
    eligible=[c for c in candidates if c["validation"]["trades"]>=30]
    chosen=max(eligible,key=lambda c:c["validation"]["net_return"]) if eligible else candidates[0]
    # Diagnostic history is inspected once AFTER all selection, cannot select or promote.
    p,act=pnl_series(predictions[chosen["name"]],a,ts,meta,chosen["threshold"])
    chosen["historical_diagnostic"]=metrics(p[audit],act[audit],ts[audit])
    chosen["historically_qualified"]=(chosen["validation"]["mean_daily_lower95"]>0 and
       chosen["stress_validation"]["net_return"]>0 and chosen["validation"]["max_drawdown"]<=.10)
    # Keep simple baselines fixed before the future period. Failed candidates remain research-only.
    frozen=[dict(name=chosen["name"] if chosen["historically_qualified"] else "zero",
                 threshold=chosen["threshold"] if chosen["historically_qualified"] else 1.,label="candidate"),
            dict(name="momentum",threshold=.004,label="momentum"),
            dict(name="reversal",threshold=.004,label="reversal"),
            dict(name="zero",threshold=1.,label="cash")]
    write(run/"development.json",dict(candidates=candidates,selected=chosen,gpu=gpu,
          caution="Previously inspected history; next-open proxy omits exact execution latency/depth. No promotion."))
    protocol.update(frozen=frozen,selected=chosen,frozen_ms=int(time.time()*1000))
    protocol["future_start_ms"]=((protocol["frozen_ms"]//STEP)+1)*STEP
    protocol["future_end_ms"]=protocol["future_start_ms"]+14*86400000
    protocol["artifact_hashes"]={p.name:digest(p) for p in run.iterdir() if p.suffix in (".pt",".npy",".npz")}
    write(run/"protocol.json",protocol)
    write(run/"frozen.json",dict(protocol_sha256=digest(run/"protocol.json"),created_ms=int(time.time()*1000)))
    print(json.dumps(dict(run=str(run),selected=chosen,gpu=gpu)),flush=True)

def predict(run,a,names):
    s=np.load(run/"scaler.npz")
    x=features(a)[-1]
    z=transform(x,s["mean"],s["std"])
    result={"zero":np.zeros(len(SYMBOLS)),"momentum":x[:,0],"reversal":-x[:,0]}
    if "ridge" in names:
        r=np.load(run/"ridge.npy");result["ridge"]=z@r[:8]+r[8]
    for name in names:
        if name.startswith("mlp-"):
            net=Net();net.load_state_dict(torch.load(run/(name+".pt"),map_location="cpu",weights_only=True));net.eval()
            with torch.no_grad():result[name]=net(torch.from_numpy(z)).numpy()/100
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--run",type=pathlib.Path,required=True)
    train(p.parse_args().run)
