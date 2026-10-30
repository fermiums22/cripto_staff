"""Bounded, resumable CUDA model factory; historical results are diagnostic only.

Never changes a PAPER wallet, frozen trial, service or credential. A fixed manifest
prevents repeated fitting on the same dataset from masquerading as new evidence.
"""
import argparse
import ctypes
import fcntl
import hashlib
import json
import os
import pathlib
import time
import numpy as np
import torch
from torch import nn
from brain_research import ROOT, STORE, SYMBOLS, STEP, features, load_data, write, digest
from brain_factory_models import SequenceModel

KINDS = ("ridge", "xgboost", "mlp", "tcn", "gru", "lstm", "transformer", "moe")
LENGTH = 16
HORIZONS = (1, 4)
SEED = 7301


def thermal():
    nv = ctypes.CDLL('/opt/nvidia-driver/libnvidia-ml.so.1')
    handle, temp = ctypes.c_void_p(), ctypes.c_uint()
    if nv.nvmlInit_v2() != 0:
        raise RuntimeError('GPU telemetry unavailable')
    try:
        if nv.nvmlDeviceGetHandleByIndex_v2(0,ctypes.byref(handle)) != 0:
            raise RuntimeError('GPU telemetry handle unavailable')
        if nv.nvmlDeviceGetTemperature(handle,0,ctypes.byref(temp)) != 0:
            raise RuntimeError('GPU temperature unavailable')
        if temp.value >= 80:
            raise RuntimeError('GPU thermal guard: retry after cooling')
        return temp.value
    finally:
        nv.nvmlShutdown()


def split_indices(n, horizon):
    first, second = int(n*.55), int(n*.70)
    return (np.arange(32,first-horizon-1),
            np.arange(first+LENGTH,second-horizon-1),
            np.arange(second+LENGTH,n))


def windows(z, ids):
    return np.stack([z[i-LENGTH+1:i+1] for i in ids]).astype('float32')


def save_checkpoint(path, state):
    tmp = path.with_suffix('.tmp')
    with tmp.open('wb') as f:
        torch.save(state,f); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)


def train_neural(kind, z, y, train, early, directory, manifest_hash, max_epochs=40):
    torch.manual_seed(SEED)
    net = SequenceModel(kind).cuda()
    optimizer = torch.optim.AdamW(net.parameters(),lr=.001,weight_decay=.01)
    scaler = torch.amp.GradScaler('cuda')
    path = directory/'checkpoint.pt'
    best, stall, start, weights = float('inf'),0,0,None
    if path.exists():
        state = torch.load(path,weights_only=False,map_location='cpu')
        if state['manifest_hash'] != manifest_hash:
            raise ValueError('Checkpoint belongs to different data/code/protocol')
        net.load_state_dict(state['model']); optimizer.load_state_dict(state['optimizer'])
        scaler.load_state_dict(state['scaler'])
        torch.set_rng_state(state['rng']); torch.cuda.set_rng_state_all(state['cuda_rng'])
        best, stall, start, weights = state['best'],state['stall'],state['epoch']+1,state['best_weights']
    for epoch in range(start,max_epochs):
        if stall >= 6: break
        temperature = thermal()
        net.train()
        order = train[torch.randperm(len(train)).numpy()]
        for offset in range(0,len(order),128):
            if offset % 1024 == 0: thermal()
            ids = order[offset:offset+128]
            tx = torch.from_numpy(windows(z,ids)).cuda()
            ty = torch.from_numpy(y[ids]*100).cuda()
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast('cuda',dtype=torch.float16):
                loss = nn.functional.smooth_l1_loss(net(tx),ty,beta=.5)
            if not torch.isfinite(loss): raise RuntimeError('nonfinite training loss')
            scaler.scale(loss).backward(); scaler.unscale_(optimizer)
            nn.utils.clip_grad_norm_(net.parameters(),1.)
            scaler.step(optimizer); scaler.update()
        prediction = predict_neural(net,z,early)
        val = float(np.mean((prediction-y[early])**2))
        if not np.isfinite(val): raise RuntimeError('nonfinite validation loss')
        if val < best-1e-10:
            best,stall = val,0
            weights = {k:v.detach().cpu().clone() for k,v in net.state_dict().items()}
        else: stall += 1
        save_checkpoint(path,dict(manifest_hash=manifest_hash,epoch=epoch,best=best,stall=stall,
            model=net.state_dict(),optimizer=optimizer.state_dict(),scaler=scaler.state_dict(),
            best_weights=weights,rng=torch.get_rng_state(),cuda_rng=torch.cuda.get_rng_state_all()))
        write(directory/'progress.json',dict(epoch=epoch,best_mse=best,stall=stall,
            temperature=temperature,peak_vram=torch.cuda.max_memory_allocated(),updated_ms=int(time.time()*1000)))
    if weights is None: raise RuntimeError('No finite checkpoint')
    net.load_state_dict(weights)
    save_checkpoint(directory/'model.pt',weights)
    return net


def predict_neural(net,z,ids):
    net.eval(); parts=[]
    with torch.no_grad():
        for offset in range(0,len(ids),128):
            tx=torch.from_numpy(windows(z,ids[offset:offset+128])).cuda()
            # Full precision validation avoids reduced-precision attention fast paths.
            parts.append(net(tx).float().cpu().numpy()/100)
    return np.concatenate(parts)


def replay(pred,a,ts,meta,ids,horizon,extra_cost=0.):
    """Diagnostic 1x shared $15 wallet; next-open fills, no overlapping holdings.

    Historical candles cannot establish depth/latency/partial fill realism.
    This deliberately cannot grant live or PAPER readiness.
    """
    cash=15.; peak=15.; max_dd=0.; next_index=-1; rows=[]
    for local,i in enumerate(ids):
        if i < next_index: continue
        scores=pred[local]
        symbol=int(np.argmax(np.abs(scores))); score=float(scores[symbol])
        if not np.isfinite(score) or abs(score) < .003: continue
        side=1 if score>0 else -1
        entry_index=i+1; exit_index=i+1+horizon
        entry=float(a[entry_index,symbol,1]); exit_price=float(a[exit_index,symbol,1])
        lot=meta[SYMBOLS[symbol]]['instrument']['lotSizeFilter']
        step=float(lot['qtyStep']); qty=np.floor(min(12.,cash*.8)/entry/step)*step
        if qty < float(lot['minOrderQty']) or qty*entry < float(lot.get('minNotionalValue',5)):
            continue
        notional=qty*entry
        funding=0.
        for f in meta[SYMBOLS[symbol]]['funding']:
            if ts[entry_index] < int(f['fundingRateTimestamp']) <= ts[exit_index]:
                # No historical event mark: conservative charge bound, no credits.
                bound=float(np.max(a[entry_index:exit_index+1,symbol,2]))
                funding += qty*bound*max(0.,side*float(f['fundingRate']))
        costs=notional*(.0012+.0006+.0004+extra_cost)
        pnl=qty*(exit_price-entry)*side-costs-funding
        # Adverse intrabar mark gives a conservative drawdown proxy without stop claims.
        adverse=float(np.min(a[entry_index:exit_index,symbol,3]) if side>0 else
                      np.max(a[entry_index:exit_index,symbol,2]))
        trough=cash+qty*(adverse-entry)*side-costs-funding
        max_dd=max(max_dd,1-trough/peak)
        cash+=pnl; peak=max(peak,cash); max_dd=max(max_dd,1-cash/peak)
        rows.append(dict(ms=int(ts[exit_index]),symbol=SYMBOLS[symbol],pnl=float(pnl),
                         costs=float(costs+funding),regime='up' if a[i,0,4]>a[i-16,0,4] else 'down'))
        next_index=exit_index
        if cash<=0 or max_dd>.10: break
    days=np.arange(ts[ids[0]]//86400000,ts[ids[-1]+horizon+1]//86400000+1)
    daily=np.array([sum(r['pnl'] for r in rows if r['ms']//86400000==d) for d in days])
    return dict(final_equity=cash,net_pnl=cash-15.,drawdown=max_dd,trades=len(rows),
        costs=sum(r['costs'] for r in rows),daily=daily.tolist(),
        regimes={reg:dict(trades=sum(r['regime']==reg for r in rows),
                         pnl=sum(r['pnl'] for r in rows if r['regime']==reg)) for reg in ['up','down']})


def compare(candidate,controls,trials):
    rng=np.random.default_rng(SEED)
    c=np.array(candidate['daily']); ids=rng.integers(0,len(c),(20000,len(c)))
    # Bonferroni across fixed architecture/horizon family AND three controls.
    alpha=.05/(trials*len(controls))
    bounds={k:float(np.quantile((c-np.array(v['daily']))[ids].mean(1),alpha)) for k,v in controls.items()}
    return bounds


def run(directory, dataset=None):
    directory.mkdir(parents=True,exist_ok=True)
    lock=(directory/'factory.lock').open('a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (directory/'summary.json').exists(): return
    if not torch.cuda.is_available(): raise RuntimeError('CUDA required')
    torch.cuda.set_per_process_memory_fraction(.45)
    torch.set_num_threads(2); os.nice(10)
    if dataset is None:
        ts,a,hashes,meta=load_data()
    else:
        with np.load(dataset/'bars.npz',allow_pickle=False) as data:
            ts,a=data['ts'],data['bars']
        meta=json.loads((dataset/'metadata.json').read_text())
        hashes={n:digest(dataset/n) for n in ('bars.npz','metadata.json','dataset.json')}
        if len(ts)<1000 or np.any(np.diff(ts)!=60000) or a.shape!=(len(ts),len(SYMBOLS),6):
            raise ValueError('Minute data must be aligned and continuous')
    manifest=dict(version=2,seed=SEED,kinds=KINDS,horizons=HORIZONS,length=LENGTH,
        dataset=str(dataset) if dataset else 'legacy-15m',bar_interval_ms=int(ts[1]-ts[0]),
        source_hashes=hashes,code_hashes={n:digest(ROOT/n) for n in
        ['brain_factory.py','brain_factory_models.py','brain_research.py']},
        history_end_ms=int(ts[-1]),historical_is_independent=False,threshold=.003,
        max_epochs=40,patience=6,ready=False,initial_equity=15.,max_notional=12.,
        costs='taker .0006 + slippage .0003 per side; spread .0004 roundtrip; stress +.001',
        limitation='Candle execution proxy, not independent full-depth PAPER evidence')
    manifest=json.loads(json.dumps(manifest))
    path=directory/'manifest.json'
    if path.exists():
        if json.loads(path.read_text()) != manifest: raise ValueError('Frozen factory manifest changed')
    else: write(path,manifest)
    manifest_hash=digest(path)
    snapshot=directory/'source';snapshot.mkdir(exist_ok=True)
    for name,expected in manifest['code_hashes'].items():
        target=snapshot/name
        if not target.exists(): target.write_bytes((ROOT/name).read_bytes())
        if digest(target)!=expected: raise ValueError('Source snapshot mismatch')
    x=features(a); reports=[]
    for horizon in HORIZONS:
        y=(a[1+horizon:,:,1]/a[1:-horizon,:,1]-1).astype('float32')
        train,early,selection=split_indices(len(y),horizon)
        mean=x[:train[-1]+1].mean((0,1)); std=np.maximum(x[:train[-1]+1].std((0,1)),1e-6)
        z=np.clip((x-mean)/std,-10,10).astype('float32')
        controls={k:replay(v,a,ts,meta,selection,horizon) for k,v in
            {'cash':np.zeros_like(y[selection]),'momentum':x[selection,:,0],
             'reversal':-x[selection,:,0]}.items()}
        for kind in KINDS:
            trial=directory/(kind+'-'+str(horizon)); trial.mkdir(exist_ok=True)
            if (trial/'result.json').exists():
                reports.append(json.loads((trial/'result.json').read_text())); continue
            thermal(); torch.cuda.reset_peak_memory_stats()
            np.savez(trial/'scaler.npz',mean=mean,std=std)
            print(json.dumps(dict(event='start',kind=kind,horizon=horizon)),flush=True)
            try:
                if kind=='ridge':
                    design=np.c_[z[train].reshape(len(train),-1),np.ones(len(train))]
                    weights=np.linalg.solve(design.T@design+10*np.eye(design.shape[1]),design.T@y[train])
                    np.save(trial/'model.npy',weights)
                    pred=np.c_[z[selection].reshape(len(selection),-1),np.ones(len(selection))]@weights
                elif kind=='xgboost':
                    import xgboost as xgb
                    class Guard(xgb.callback.TrainingCallback):
                        def after_iteration(self,model,epoch,evals_log):
                            if epoch%10==0: thermal()
                            return False
                    pred=np.zeros_like(y[selection])
                    for s in range(len(SYMBOLS)):
                        thermal()
                        model=xgb.XGBRegressor(n_estimators=200,max_depth=3,learning_rate=.03,
                            n_jobs=2,device='cuda',tree_method='hist',random_state=SEED,
                            early_stopping_rounds=12,callbacks=[Guard()])
                        model.fit(z[train].reshape(len(train),-1),y[train,s],
                            eval_set=[(z[early].reshape(len(early),-1),y[early,s])],verbose=False)
                        pred[:,s]=model.predict(z[selection].reshape(len(selection),-1))
                        model.save_model(trial/(SYMBOLS[s]+'.json'))
                else:
                    net=train_neural(kind,z,y,train,early,trial,manifest_hash)
                    pred=predict_neural(net,z,selection)
                    del net; torch.cuda.empty_cache()
                if not np.isfinite(pred).all(): raise ValueError('nonfinite prediction')
                result=replay(pred,a,ts,meta,selection,horizon)
                stress=replay(pred,a,ts,meta,selection,horizon,.001)
                bounds=compare(result,controls,len(KINDS)*len(HORIZONS))
                qualified=(result['trades']>=100 and result['net_pnl']>0 and stress['net_pnl']>0
                           and result['drawdown']<=.10 and all(v>0 for v in bounds.values())
                           and all(v['trades']>=20 and v['pnl']>0 for v in result['regimes'].values()))
                report=dict(kind=kind,horizon=horizon,result=result,stress=stress,controls=controls,
                    paired_daily_lower_bounds=bounds,development_pass=qualified,ready=False,
                    manifest_hash=manifest_hash,status='candidate_for_execution_audit' if qualified else 'rejected')
                write(trial/'result.json',report); reports.append(report)
                print(json.dumps(dict(event='result',kind=kind,horizon=horizon,pnl=result['net_pnl'],
                                      status=report['status'])),flush=True)
            except Exception as exc:
                write(trial/'error.json',dict(error=type(exc).__name__,reason=str(exc)[:400],
                                             updated_ms=int(time.time()*1000)))
                raise
    write(directory/'summary.json',dict(reports=reports,ready=False,manifest_hash=manifest_hash,
        next_action='Collect future evidence; rejected architectures cannot be promoted',
        completed_ms=int(time.time()*1000)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--directory',type=pathlib.Path,required=True)
    parser.add_argument('--dataset',type=pathlib.Path)
    args=parser.parse_args();run(args.directory,args.dataset)
