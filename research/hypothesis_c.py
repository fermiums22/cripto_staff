"""C: choose coin/direction from causally simultaneous, after-cost ranking labels."""
import copy
import json
from pathlib import Path
import numpy as np
import torch
from torch import nn
from brain_archive_stream import sha
from brain_factory import thermal,save_checkpoint
from brain_impulse_data import execution_label,atomic_json
from brain_impulse_dataset import ASSETS
from research.hypothesis_b import FEATURES as MICRO


def vector(x,asset,side,kind):
    z=np.asarray(x,dtype='float32')
    if kind=='B':z=z[list(MICRO)]
    return np.r_[z,np.eye(4,dtype='float32')[asset],float(side)].astype('float32')


def groups(tape,instruments,kind):
    histories=[]
    for k,symbol in enumerate(ASSETS):
        bm=tape['bs']==k;fm=tape['fs']==k
        bt=tape['bt'][bm];depth=tape['depth'][bm];ft=tape['ft'][fm];fx=tape['fx'][fm]
        gaps=np.r_[0,np.cumsum(np.diff(bt)>7000)]
        histories.append((bt,depth,ft,fx,gaps))
    result=[]
    start=((int(tape['ft'][0])+4999)//5000)*5000;end=int(tape['bt'][-1])-125000
    for now in range(start,end,5000):
        xs=[];ys=[]
        for k,(bt,depth,ft,fx,gaps) in enumerate(histories):
            f=int(np.searchsorted(ft,now,side='right'))-1
            if f<0 or now-ft[f]>1500:continue
            e=int(np.searchsorted(bt,now+1000))
            if e>=len(bt) or bt[e]-now-1000>1500:continue
            z=int(np.searchsorted(bt,int(bt[e])+121000))
            if z>=len(bt) or bt[z]-bt[e]-121000>1500 or gaps[z]!=gaps[e] or now//3600000!=bt[z]//3600000:continue
            def quote(i):return dict(bids=[tuple(v) for v in depth[i,0] if v[1]>0],asks=[tuple(v) for v in depth[i,1] if v[1]>0])
            for side in (1,-1):
                label=execution_label(quote(e),quote(z),instruments[ASSETS[k]]['lotSizeFilter'],side,notional=12.)
                if label is not None:xs.append(vector(fx[f],k,side,kind));ys.append(label['net_return'])
        if len(xs)>=2:result.append((np.asarray(xs),np.asarray(ys,dtype='float32')))
    if not result:raise ValueError('No causal ranking groups')
    return result


class RankNet(nn.Module):
    def __init__(self,n):
        super().__init__();self.net=nn.Sequential(nn.Linear(n,32),nn.SiLU(),nn.Linear(32,16),nn.SiLU(),nn.Linear(16,1))
    def forward(self,x):return self.net(x).squeeze(-1)


def tensors(data,mean,std):
    x=np.zeros((len(data),8,len(mean)),dtype='float32');y=np.zeros((len(data),8),dtype='float32');mask=np.zeros_like(y,dtype=bool)
    for i,(a,b) in enumerate(data):
        n=len(a);x[i,:n]=np.clip((a-mean)/std,-8,8);y[i,:n]=b*100;mask[i,:n]=True
    return [torch.from_numpy(a).cuda() for a in (x,y,mask)]


def fit(train,early,folder,identity):
    import xgboost as xgb
    folder.mkdir(parents=True,exist_ok=True);torch.manual_seed(7301);torch.set_num_threads(2)
    flat=np.concatenate([a for a,b in train]);labels=np.concatenate([b for a,b in train]);sizes=[len(a) for a,b in train]
    mean=flat.mean(0);std=np.maximum(flat.std(0),1e-6)
    model_file=folder/'boost.ubj';progress=folder/'boost-progress.json';rounds=0;booster=None
    matrix=xgb.DMatrix(flat,label=labels,group=sizes,nthread=2)
    if progress.exists():
        saved=json.loads(progress.read_text())
        if saved['identity']!=identity:raise ValueError('Boost checkpoint identity changed')
        rounds=saved['rounds'];booster=xgb.Booster();booster.load_model(folder/saved['file'])
    for stop in range(rounds+4,33,4):
        thermal();booster=xgb.train(dict(objective='rank:pairwise',tree_method='hist',device='cuda',max_depth=3,
            max_bin=64,eta=.05,reg_lambda=10,seed=7301,nthread=2),matrix,num_boost_round=4,xgb_model=booster)
        if json.loads(booster.save_config())['learner']['generic_param']['device']!='cuda:0':raise RuntimeError('GPU ranking not active')
        target=folder/f'boost-{stop}.ubj';booster.save_model(target)
        atomic_json(progress,dict(rounds=stop,file=target.name,identity=identity))
    booster.save_model(model_file);booster.set_param({'device':'cpu'})
    tx,ty,tm=tensors(train,mean,std);vx,vy,vm=tensors(early,mean,std)
    net=RankNet(flat.shape[1]).cuda();opt=torch.optim.AdamW(net.parameters(),lr=.002)
    best=-float('inf');best_state=None;history=[];start=0;path=folder/'neural.pt'
    if path.exists():
        saved=torch.load(path,weights_only=False,map_location='cuda')
        if saved['identity']!=identity:raise ValueError('Neural checkpoint identity changed')
        net.load_state_dict(saved['state']);opt.load_state_dict(saved['optimizer']);best=saved['best'];best_state=saved['best_state'];history=saved['history'];start=saved['epoch']+1
    for epoch in range(start,8):
        thermal()
        for i in range(0,len(tx),128):
            score=net(tx[i:i+128]);mask=tm[i:i+128];y=ty[i:i+128]
            logits=score.masked_fill(~mask,-1e9);target=(y/.2).masked_fill(~mask,-1e9).softmax(-1)
            loss=-(target*logits.log_softmax(-1)).sum(-1).mean()+.1*nn.functional.smooth_l1_loss(score[mask],y[mask])
            opt.zero_grad();loss.backward();nn.utils.clip_grad_norm_(net.parameters(),1.);opt.step()
        with torch.no_grad():
            choices=net(vx).masked_fill(~vm,-1e9).argmax(-1);value=float(vy.gather(1,choices[:,None]).mean()/100)
        if value>best:best=value;best_state=copy.deepcopy(net.state_dict())
        history.append(dict(epoch=epoch,early_top_choice_mean_net=value))
        save_checkpoint(path,dict(identity=identity,state=net.state_dict(),optimizer=opt.state_dict(),best=best,best_state=best_state,
            history=history,epoch=epoch,mean=mean,std=std))
    net.load_state_dict(best_state);net.eval()
    with (folder/'scaler.npz').open('wb') as f:np.savez(f,mean=mean,std=std)
    atomic_json(folder/'result.json',dict(train_groups=len(train),early_groups=len(early),history=history,
        objective='relative ranking of executable net labels; score is not calibrated expected profit',ready=False))
    def predict(x):
        x=np.asarray(x,dtype='float32')
        with torch.no_grad():n=net(torch.from_numpy(np.clip((x-mean)/std,-8,8)).cuda()).cpu().numpy()
        b=booster.predict(xgb.DMatrix(x,nthread=2));return b,n
    return predict


if __name__=='__main__':
    from research.compare import main
    main('C')
