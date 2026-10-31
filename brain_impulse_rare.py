"""Class-balanced rare-event prediction, separated from net-value prediction.

One fixed model, bounded epochs. All periods are historical development only;
no successful classifier is automatically a profitable strategy or live model.
"""
import argparse
import copy
import json
from pathlib import Path
import numpy as np
import torch
from torch import nn
from brain_archive_stream import sha
from brain_factory import thermal,save_checkpoint
from brain_impulse_data import atomic_json
from brain_impulse_dataset import ASSETS
from brain_impulse_opportunities import read_day,thin,stats


def average_precision(labels,scores):
    y=np.asarray(labels,dtype=bool);s=np.asarray(scores)
    if not len(y) or not y.any():return None
    order=np.argsort(-s,kind='stable');y=y[order];s=s[order]
    ends=np.r_[np.flatnonzero(s[:-1]!=s[1:]),len(s)-1]
    tp=np.cumsum(y)[ends];precision=tp/(ends+1);recall=tp/y.sum()
    return float(np.sum(np.diff(np.r_[0.,recall])*precision))


class RareNet(nn.Module):
    def __init__(self):
        super().__init__();self.body=nn.Sequential(nn.Linear(34,48),nn.SiLU(),nn.Linear(48,24),nn.SiLU())
        self.event=nn.Linear(24,2);self.value=nn.Linear(24,2)
    def forward(self,x):
        h=self.body(x);return self.event(h),self.value(h)


def combine(days):
    return {k:np.concatenate([d[k] for d in days]) for k in ('x','y','symbols','t')}


def features(d,mean,std):
    return np.concatenate([np.clip((d['x']-mean)/std,-8,8),np.eye(4,dtype='float32')[d['symbols']]],1).astype('float32')


def predict(net,x):
    logits=[];values=[]
    with torch.no_grad():
        for start in range(0,len(x),4096):
            a,b=net(torch.from_numpy(x[start:start+4096]).cuda());logits.append(a.cpu().numpy());values.append(b.cpu().numpy()/100)
    return np.concatenate(logits),np.concatenate(values)


def chosen(d,score,side,threshold):
    ids=[]
    for k in range(4):ids.extend(thin(d['t'],(d['symbols']==k)&(score>=threshold)).tolist())
    ids=np.asarray(sorted(ids),dtype='int64');out=d['y'][ids,6+side[ids]]
    return dict(**stats(out),by_symbol={s:stats(out[d['symbols'][ids]==i]) for i,s in enumerate(ASSETS)},
        sample_indices=ids.tolist(),signal_ms=d['t'][ids].tolist(),sides=side[ids].tolist(),
        proxy_only=True,ready=False)


def run(campaign,output):
    output.mkdir(parents=True,exist_ok=True);torch.manual_seed(7301);torch.set_num_threads(2)
    train_days=[f'2026-10-{i:02d}' for i in range(2,6)]
    plan=dict(train=train_days,early='2026-10-06',calibration='2026-10-07',score=['2026-10-10','2026-10-11'],
        horizon_ms=120000,event_net_threshold=.001,selection_quantile=.995,max_epochs=12,patience=3,
        seed=7301,source={n:sha(Path(__file__).parent/n) for n in ('brain_impulse_rare.py','brain_impulse_opportunities.py','brain_impulse_dataset.py','brain_factory.py')},
        class_weight_cap=100,scope='historical_development_only',ready=False)
    for day in train_days+[plan['early'],plan['calibration']]+plan['score']:
        plan.setdefault('datasets',{})[day]=sha(campaign/day/'dataset/dataset.json')
    pp=output/'plan.json'
    if pp.exists() and json.loads(pp.read_text())!=plan:raise ValueError('Rare experiment plan changed')
    if not pp.exists():atomic_json(pp,plan)
    if (output/'result.json').exists():return
    data=combine([read_day(campaign,day) for day in train_days]);early=read_day(campaign,plan['early'])
    mean=data['x'].mean(0);std=np.maximum(data['x'].std(0),1e-6)
    x=features(data,mean,std);ex=features(early,mean,std);target=data['y'][:,6:8];ey=early['y'][:,6:8]
    prevalence=np.mean(target>.001,axis=0);weight=np.minimum((1-prevalence)/np.maximum(prevalence,1e-6),100)
    w=torch.tensor(weight,dtype=torch.float32,device='cuda');net=RareNet().cuda();opt=torch.optim.AdamW(net.parameters(),lr=.001,weight_decay=.001)
    history=[];best=-1.;best_weights=None;stalls=0;start=0;checkpoint=output/'checkpoint.pt'
    if checkpoint.exists():
        saved=torch.load(checkpoint,weights_only=False,map_location='cuda')
        if saved['plan_sha256']!=sha(pp):raise ValueError('Checkpoint identity mismatch')
        net.load_state_dict(saved['state']);opt.load_state_dict(saved['optimizer']);history=saved['history'];start=saved['epoch']+1
        best=saved['best'];best_weights=saved['best_weights'];stalls=saved['stalls']
    for epoch in range(start if stalls<3 else 12,12):
        thermal();atomic_json(output/'status.json',dict(stage='training',epoch=epoch,ready=False));net.train()
        # Fixed epoch-specific permutations make interruption/restart reproducible.
        ids=np.random.default_rng(7301+epoch).permutation(len(x))
        for offset in range(0,len(ids),2048):
            batch=ids[offset:offset+2048];tx=torch.from_numpy(x[batch]).cuda();ty=torch.from_numpy(target[batch]).cuda()
            logits,value=net(tx);loss=nn.functional.binary_cross_entropy_with_logits(logits,(ty>.001).float(),pos_weight=w)
            loss=loss+.1*nn.functional.smooth_l1_loss(value,ty*100,beta=.2)
            if not torch.isfinite(loss):raise ValueError('Nonfinite rare-event loss')
            opt.zero_grad();loss.backward();nn.utils.clip_grad_norm_(net.parameters(),1.);opt.step()
        net.eval();elog,_=predict(net,ex);ap=average_precision(ey.ravel()>.001,elog.ravel()) or 0.
        if ap>best:best=ap;best_weights=copy.deepcopy(net.state_dict());stalls=0
        else:stalls+=1
        history.append(dict(epoch=epoch,early_average_precision=ap,early_prevalence=float(np.mean(ey>.001))))
        save_checkpoint(checkpoint,dict(state=net.state_dict(),optimizer=opt.state_dict(),history=history,epoch=epoch,
            best=best,best_weights=best_weights,stalls=stalls,mean=mean,std=std,plan_sha256=sha(pp)))
        if stalls>=3:break
    net.load_state_dict(best_weights);net.eval();del data,x,early,ex
    cal=read_day(campaign,plan['calibration']);clog,cvalue=predict(net,features(cal,mean,std))
    # Weighted BCE is not a calibrated probability. Fit a separate affine
    # logit calibration on its own day using unweighted log loss.
    raw=torch.tensor(clog,device='cuda');labels=torch.tensor(cal['y'][:,6:8]>.001,device='cuda',dtype=torch.float32)
    scale=nn.Parameter(torch.ones(2,device='cuda'));bias=nn.Parameter(-w.log().detach().clone())
    optimizer=torch.optim.LBFGS([scale,bias],lr=.3,max_iter=40,line_search_fn='strong_wolfe')
    def closure():
        optimizer.zero_grad();loss=nn.functional.binary_cross_entropy_with_logits(raw*scale.clamp(.05,20)+bias,labels);loss.backward();return loss
    optimizer.step(closure);scale=scale.detach().clamp(.05,20).cpu().numpy();bias=bias.detach().cpu().numpy()
    calibrate=lambda a:1/(1+np.exp(-np.clip(a*scale+bias,-30,30)))
    cp=calibrate(clog)
    thresholds={name:float(np.quantile(score,.995)) for name,score in dict(event=cp.max(1),net_value=cvalue.max(1),volatility=cal['x'][:,5]).items()}
    atomic_json(output/'calibration.json',dict(scale=scale.tolist(),bias=bias.tolist(),thresholds=thresholds,day=plan['calibration'],ready=False))
    save_checkpoint(output/'model.pt',dict(state=net.state_dict(),mean=mean,std=std,scale=scale,bias=bias,thresholds=thresholds,plan_sha256=sha(pp)))
    reports={}
    for day in plan['score']:
        atomic_json(output/'status.json',dict(stage='scoring_fixed_hypothesis',day=day,ready=False))
        d=read_day(campaign,day);logits,value=predict(net,features(d,mean,std));prob=calibrate(logits);y=d['y'][:,6:8]>.001
        reports[day]=dict(event_ap=average_precision(y.ravel(),prob.ravel()),prevalence=float(y.mean()),
            volatility_ap=average_precision(y.ravel(),np.repeat(d['x'][:,5],2)),
            brier=float(np.mean((prob-y)**2)),prior_brier=float(np.mean((np.mean(cal['y'][:,6:8]>.001,axis=0)-y)**2)),
            choices=dict(event=chosen(d,prob.max(1),prob.argmax(1),thresholds['event']),
                net_value=chosen(d,value.max(1),value.argmax(1),thresholds['net_value']),
                volatility=chosen(d,d['x'][:,5],(d['x'][:,0]<0).astype('int64'),thresholds['volatility'])))
    atomic_json(output/'result.json',dict(reports=reports,history=history,train_prevalence=prevalence.tolist(),
        class_weights=weight.tolist(),ready=False,independent_evidence=False,
        model_sha256=sha(output/'model.pt'),plan_sha256=sha(pp),
        caveat='Selection and net outcomes are fixed-horizon proxies, not actual stopped portfolio fills. Historical dates previously examined.'))
    atomic_json(output/'status.json',dict(stage='complete',ready=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--campaign',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.campaign,a.output)
