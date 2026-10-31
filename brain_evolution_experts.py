"""Bounded architecture comparison on recorded tapes, development data only.

Separate impulse/leadlag/flow forecasting experts and capital allocation, versus
direct financial policy. Differentiable turnover-cost proxy is TRAINING ONLY;
held-out development action evaluation uses delayed recorded-depth execution.
"""
import argparse
import copy
import fcntl
import gzip
import json
import os
from pathlib import Path
import numpy as np
import torch
from torch import nn
from brain_archive_stream import sha
from brain_factory import thermal,save_checkpoint
from brain_impulse_data import atomic_json
from brain_impulse_dataset import ASSETS
from brain_evolution_env import ExplorationAccount

GROUPS=((0,1,2,3,4,5,6,15,16),(17,18,19,20,21,22),(7,8,9,10,11,12,13,14))


class Experts(nn.Module):
    def __init__(self,kind):
        super().__init__();self.kind=kind
        if kind=='direct':self.network=nn.Sequential(nn.Linear(120,64),nn.Tanh(),nn.Linear(64,4))
        else:
            self.forecasters=nn.ModuleList([nn.Sequential(nn.Linear(len(g),24),nn.Tanh(),nn.Linear(24,2)) for g in GROUPS])
            self.allocator=nn.Sequential(nn.Linear(24,32),nn.Tanh(),nn.Linear(32,4))

    def forward(self,x):
        if self.kind=='direct':return .25*self.network(x.flatten(-2)).tanh(),None
        forecasts=torch.stack([net(x[...,list(g)]) for g,net in zip(GROUPS,self.forecasters)],-2)
        return .25*self.allocator(forecasts.flatten(-3)).tanh(),forecasts


def grid(tape):
    # Common causal clock. No feature is read from after its decision time.
    start=((int(tape['ft'][0])+4999)//5000)*5000;end=int(tape['bt'][-1])-11000
    t=np.arange(start,end,5000,dtype='int64');x=np.zeros((len(t),4,30),dtype='float32')
    ret=np.zeros((len(t),4),dtype='float32');cost=np.zeros_like(ret);valid=np.ones(len(t),dtype=bool);observed=np.ones(len(t),dtype=bool)
    for symbol in range(4):
        fm=tape['fs']==symbol;ft=tape['ft'][fm];fx=tape['fx'][fm]
        bm=tape['bs']==symbol;bt=tape['bt'][bm];bd=tape['depth'][bm]
        if not len(ft) or not len(bt):raise ValueError('Missing instrument tape')
        fi=np.searchsorted(ft,t,side='right')-1;bi=np.searchsorted(bt,t+1000);bj=np.searchsorted(bt,t+6000)
        good=(fi>=0)&(bi<len(bt))&(bj<len(bt));fi=np.clip(fi,0,len(ft)-1);bi=np.minimum(bi,len(bt)-1);bj=np.minimum(bj,len(bt)-1)
        observed&=(ft[fi]<=t)&(t-ft[fi]<=7000)
        good&=(t-ft[fi]<=7000)&(bt[bi]-t-1000<=1500)&(bt[bj]-t-6000<=1500)
        x[:,symbol]=fx[fi];mid=(bd[:,0,0,0]+bd[:,1,0,0])/2
        ret[:,symbol]=mid[bj]/mid[bi]-1
        cost[:,symbol]=.0009+(bd[bi,1,0,0]-bd[bi,0,0,0])/(2*mid[bi])
        valid&=good
    return dict(t=t,x=x,r=ret,c=cost,valid=valid,observed=observed)


def chunks(g,length=120):
    ids=[]
    for i in range(0,len(g['t'])-length-12,length):
        end=i+length
        if not g['valid'][i:end+12].all():continue
        if g['t'][i]//3600000!=(g['t'][end+11]+6000)//3600000:continue
        ids.append(np.arange(i,end))
    if not ids:raise ValueError('No contiguous eligible training episodes')
    ids=np.asarray(ids)
    future=np.stack([g['r'][ids+j] for j in range(12)]).sum(0)
    return dict(x=g['x'][ids],r=g['r'][ids],c=g['c'][ids],future=future)


def objective(weights,returns,cost):
    previous=torch.cat([torch.zeros_like(weights[:,:1]),weights[:,:-1]],1)
    # The execution environment forces a close after at most five minutes.
    # Charge close/re-entry at each60-step boundary even for constant targets.
    reset=torch.ones((1,weights.shape[1],1),device=weights.device);reset[:,::60]=0
    previous=previous*reset
    pnl=(weights*returns).sum((1,2))
    fees=((weights-previous).abs()*cost).sum((1,2))+(weights[:,-1].abs()*cost[:,-1]).sum(1)
    fees=fees+(weights[:,59:-1:60].abs()*cost[:,59:-1:60]).sum((1,2))
    return pnl-fees,fees


def metrics(net,data):
    values=[];costs=[];turn=[]
    with torch.no_grad():
        for i in range(0,len(data['x']),64):
            w,_=net(data['x'][i:i+64]);p,c=objective(w,data['r'][i:i+64],data['c'][i:i+64]);values.extend(p.cpu().tolist());costs.extend(c.cpu().tolist())
            turn.append(float(w.abs().mean()))
    return dict(mean_episode_net=float(np.mean(values)),mean_episode_cost=float(np.mean(costs)),mean_exposure=float(np.mean(turn)),episodes=len(values))


def fit(kind,train,early,folder,plan_sha,mean,std):
    torch.manual_seed(7301);net=Experts(kind).cuda();opt=torch.optim.AdamW(net.parameters(),lr=.002,weight_decay=.001)
    path=folder/(kind+'.pt');history=[];best=-float('inf');stalls=0;best_weights=None;start=0
    if path.exists():
        saved=torch.load(path,weights_only=False,map_location='cuda')
        if saved['plan_sha256']!=plan_sha:raise ValueError('Training checkpoint changed')
        net.load_state_dict(saved['state']);opt.load_state_dict(saved['optimizer']);history=saved['history'];start=saved['epoch']+1
        best=saved['best'];best_weights=saved['best_weights'];stalls=saved['stalls']
    for epoch in range(start if stalls<4 else 20,20):
        thermal();net.train()
        for i in range(0,len(train['x']),64):
            x=train['x'][i:i+64];w,forecast=net(x);p,_=objective(w,train['r'][i:i+64],train['c'][i:i+64])
            loss=-100*p.mean()
            if forecast is not None:
                target=train['future'][i:i+64]
                direction=target[...,None].expand(*target.shape,3)*100
                occurrence=(target.abs()>.003).float()[...,None].expand(*target.shape,3)
                loss=loss+.1*nn.functional.smooth_l1_loss(forecast[...,0],direction)
                loss=loss+.02*nn.functional.binary_cross_entropy_with_logits(forecast[...,1],occurrence)
            if not torch.isfinite(loss):raise ValueError('Nonfinite policy loss')
            opt.zero_grad();loss.backward();nn.utils.clip_grad_norm_(net.parameters(),1.);opt.step()
        net.eval();tr=metrics(net,train);ev=metrics(net,early);value=ev['mean_episode_net']
        if value>best:best=value;best_weights=copy.deepcopy(net.state_dict());stalls=0
        else:stalls+=1
        history.append(dict(epoch=epoch,train=tr,new_training_period=ev))
        save_checkpoint(path,dict(state=net.state_dict(),optimizer=opt.state_dict(),history=history,epoch=epoch,
            best=best,best_weights=best_weights,stalls=stalls,plan_sha256=plan_sha,mean=mean,std=std))
        atomic_json(folder/(kind+'-learning.json'),dict(history=history,ready=False))
        if stalls>=4:break
    net.load_state_dict(best_weights);return net


def execute(tape,g,weights,instruments):
    # Four isolated25 virtual subaccounts =100 total; no old wallet is touched.
    accounts=[ExplorationAccount(instruments,initial_cash=25.) for _ in ASSETS]
    bi=gi=0;peak=100.;dd=0.;end=int(tape['bt'][-1]);closing=end-310000
    while bi<len(tape['bt']) or gi<len(g['t']):
        bt=int(tape['bt'][bi]) if bi<len(tape['bt']) else 2**63-1
        gt=int(g['t'][gi]) if gi<len(g['t']) else 2**63-1
        if bt<=gt:
            k=int(tape['bs'][bi]);a=accounts[k];depth=tape['depth'][bi]
            if a.position or a.pending:
                book=dict(ts=bt,symbol=ASSETS[k],bids=[(float(p),float(q)) for p,q in depth[0] if q>0],asks=[(float(p),float(q)) for p,q in depth[1] if q>0]);a.book(book)
            eq=sum(a.equity for a in accounts);peak=max(peak,eq);dd=max(dd,1-eq/peak);bi+=1
        else:
            for k,a in enumerate(accounts):
                if a.pending or a.bankrupt:continue
                w=float(weights[gi,k]);fresh=bool(g['observed'][gi])
                if a.position:
                    close=gt>=closing or not fresh or w*a.position['side']<=.02
                    if close:a.act(dict(kind='CLOSE'),gt)
                    else:a.act(dict(kind='HOLD'),gt)
                elif fresh and gt<closing and abs(w)>.05:
                    a.act(dict(kind='BUY' if w>0 else 'SELL',symbol=ASSETS[k],fraction=min(1.,4*abs(w)),leverage=1.,stop=.03,hold_ms=300000),gt)
                else:a.act(dict(kind='NO TRADE'),gt)
            gi+=1
    reports={symbol:a.report() for symbol,a in zip(ASSETS,accounts)}
    trades=sum(r['trades'] for r in reports.values());pnl=sum(r['net_pnl'] for r in reports.values())
    attempts=sum(sum(a['kind'] in ('BUY','SELL') for a in r['actions']) for r in reports.values())
    infeasible=sum(r['rejections'].get('quantity_or_depth',0)+r['rejections'].get('margin_budget',0) for r in reports.values())
    behavior=('active_positive_development' if pnl>0 else 'active_losing') if trades else ('execution_infeasible' if infeasible else 'cash_like')
    return dict(accounts=reports,net_pnl=sum(r['net_pnl'] for r in reports.values()),net_return=sum(r['net_pnl'] for r in reports.values())/100,
        trades=trades,entry_attempts=attempts,infeasible_rejections=infeasible,behavior=behavior,
        fees=sum(r['fees'] for r in reports.values()),
        max_drawdown=dd,evidence_issues=sorted({v for r in reports.values() for v in r['evidence_issues']}),
        initial_virtual_capital=100.,ready=False,independent_evidence=False)


def run(lab,campaign,output):
    output.mkdir(parents=True,exist_ok=True)
    with (output/'worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        days=[f'2026-10-{n:02d}' for n in range(2,10)]
        if any(not (lab/'tapes'/d/'manifest.json').exists() for d in days):
            atomic_json(output/'status.json',dict(stage='waiting_for_existing_recorded_tapes',ready=False));return
        plan=dict(train=days[:4],early_training=days[4:6],development_validation=days[6:],
            source={n:sha(Path(__file__).parent/n) for n in ('brain_evolution_experts.py','brain_evolution_env.py','brain_impulse_execution.py','brain_factory.py','brain_archive_stream.py','brain_impulse_data.py','brain_impulse_dataset.py')},
            tapes={d:json.loads((lab/'tapes'/d/'manifest.json').read_text())['sha256'] for d in days},
            instruments_sha256=sha(campaign/'instrument-scenario.json'),max_epochs=20,patience=4,
            initial_virtual_capital=100,production_gate_bypass=False,independent_evidence=False,ready=False)
        pp=output/'plan.json'
        if pp.exists() and json.loads(pp.read_text())!=plan:raise ValueError('Architecture comparison plan changed')
        if not pp.exists():atomic_json(pp,plan)
        snapshot=output/'source';snapshot.mkdir(exist_ok=True)
        for name,h in plan['source'].items():
            target=snapshot/name
            if not target.exists():target.write_bytes((Path(__file__).parent/name).read_bytes())
            if sha(target)!=h:raise ValueError('Source snapshot changed')
        completed=output/'result.json'
        if completed.exists():
            result=json.loads(completed.read_text())
            for name,h in result['artifacts'].items():
                if sha(output/name)!=h:raise ValueError('Completed comparison artifact changed')
            return
        torch.set_num_threads(2);torch.cuda.set_per_process_memory_fraction(.35)
        datasets={}
        for day in days[:6]:
            p=lab/'tapes'/day/'tape.npz'
            if sha(p)!=plan['tapes'][day]:raise ValueError('Tape changed')
            with np.load(p) as f:tape={k:f[k] for k in f.files}
            datasets[day]=chunks(grid(tape));del tape
        tr={k:np.concatenate([datasets[d][k] for d in days[:4]]) for k in datasets[days[0]]}
        ev={k:np.concatenate([datasets[d][k] for d in days[4:6]]) for k in tr};del datasets
        mean=tr['x'].mean((0,1,2));std=np.maximum(tr['x'].std((0,1,2)),1e-6)
        for data in (tr,ev):
            data['x']=np.clip((data['x']-mean)/std,-8,8)
            for k,v in data.items():data[k]=torch.from_numpy(v.astype('float32')).cuda()
        torch.set_num_threads(2);models={}
        for kind in ('direct','experts'):
            atomic_json(output/'status.json',dict(stage='training',kind=kind,ready=False))
            models[kind]=fit(kind,tr,ev,output,sha(pp),mean,std)
        del tr,ev
        instruments=json.loads((campaign/'instrument-scenario.json').read_text());instruments=instruments.get('instruments',instruments)
        for day in days[6:]:
            target=output/(day+'.json.gz')
            digest=output/(day+'.sha256')
            if target.exists() and digest.exists():
                if sha(target)!=digest.read_text().strip():raise ValueError('Cached development result changed')
                continue
            p=lab/'tapes'/day/'tape.npz'
            if sha(p)!=plan['tapes'][day]:raise ValueError('Validation tape changed')
            with np.load(p) as f:tape={k:f[k] for k in f.files}
            g=grid(tape);z=np.clip((g['x']-mean)/std,-8,8).astype('float32');weights={}
            with torch.no_grad():
                for kind,net in models.items():weights[kind]=net(torch.from_numpy(z).cuda())[0].cpu().numpy()
            weights['cash']=np.zeros((len(z),4));weights['momentum']=.25*np.sign(g['x'][:,:,1])*(np.abs(g['x'][:,:,1])>.0003)
            reports={}
            for name,w in weights.items():
                atomic_json(output/'status.json',dict(stage='recorded_depth_evaluation',day=day,kind=name,ready=False))
                reports[name]=execute(tape,g,w,instruments)
            part=target.with_suffix('.part')
            with part.open('wb') as raw:
                with gzip.GzipFile(fileobj=raw,mode='wb') as f:f.write(json.dumps(reports,allow_nan=False).encode())
                raw.flush();os.fsync(raw.fileno())
            os.replace(part,target);digest.write_text(sha(target))
        atomic_json(output/'status.json',dict(stage='completed_development_comparison',ready=False,independent_evidence=False))
        summary={}
        for day in days[6:]:
            with gzip.open(output/(day+'.json.gz'),'rt') as f:rows=json.load(f)
            summary[day]={n:{k:v for k,v in row.items() if k!='accounts'} for n,row in rows.items()}
        artifacts={p.name:sha(p) for p in output.iterdir() if p.is_file() and p.suffix in ('.pt','.gz')}
        atomic_json(completed,dict(validation=summary,artifacts=artifacts,ready=False,independent_evidence=False,
            limitations=['training is a differentiable turnover-cost approximation',
                'validation uses recorded one-second depth; not tick execution',
                'four virtual subaccounts of25, different capital from earlier15 trials',
                'development history previously examined; no independent proof']))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--lab',type=Path,required=True);p.add_argument('--campaign',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.lab,a.campaign,a.output)
