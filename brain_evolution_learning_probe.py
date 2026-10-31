"""Synthetic learnability audit, NEVER Bybit profitability evidence.

Compare direct policy learning with separate event/direction experts and a learned
capital allocator. Gradient-assisted offspring and random-only offspring compete
on fresh TRAINING episodes; final synthetic holdout is accessed only once.
"""
import argparse
import copy
from pathlib import Path
import numpy as np
import torch
from torch import nn
from brain_archive_stream import sha
from brain_impulse_data import atomic_json
from brain_factory import save_checkpoint,thermal


class Policy(nn.Module):
    def __init__(self,kind):
        super().__init__();self.kind=kind
        if kind=='direct':self.net=nn.Sequential(nn.Linear(16,32),nn.Tanh(),nn.Linear(32,8))
        else:
            self.event=nn.Sequential(nn.Linear(4,16),nn.Tanh(),nn.Linear(16,2))
            self.allocator=nn.Sequential(nn.Linear(8,16),nn.Tanh(),nn.Linear(16,8))
        self.cash=nn.Parameter(torch.tensor(0.))

    def forward(self,x):
        events=None
        if self.kind=='direct':h=self.net(x.flatten(-2))
        else:events=self.event(x);h=self.allocator(events.flatten(-2))
        direction=h[...,:4].tanh();mass=torch.cat([h[...,4:],self.cash.expand(*h.shape[:-1],1)],-1).softmax(-1)[...,:4]
        return direction*mass,events


def episodes(seed,count,scenario,device='cuda'):
    rng=np.random.default_rng(seed);x=rng.normal(size=(count,64,4,4)).astype('float32')
    # x[...,0] is a contemporaneously observable cue, independent of future noise.
    signal=.006*np.tanh(x[...,0]) if scenario!='noise' else np.zeros(x.shape[:-1])
    noise=0. if scenario=='clean' else .004
    returns=(signal+rng.normal(0,noise,size=signal.shape)).astype('float32')
    return torch.from_numpy(x).to(device),torch.from_numpy(returns).to(device)


def financial(weights,returns,cost):
    previous=torch.cat([torch.zeros_like(weights[:,:1]),weights[:,:-1]],1)
    gross=(weights*returns).sum((1,2))
    turnover=(weights-previous).abs().sum((1,2))+weights[:,-1].abs().sum(1)
    net=gross-cost*turnover
    return net,gross,turnover


def score(model,x,y,cost):
    with torch.no_grad():
        w,_=model(x);net,gross,turnover=financial(w,y,cost)
    return net.cpu().numpy(),dict(net=float(net.mean()),gross=float(gross.mean()),
        costs=float((gross-net).mean()),turnover=float(turnover.mean()),
        active_fraction=float((w.abs().sum(-1)>.01).float().mean()))


def experiment(kind,scenario,seed,output,generations=12):
    torch.manual_seed(seed);parent=Policy(kind).cuda();initial=copy.deepcopy(parent)
    cost=0. if scenario=='clean' else .001  # explicit fee+halfspread+slip, each side
    history=[];stalls=0
    checkpoint=output/f'{kind}-{scenario}-{seed}.pt';start=0
    if checkpoint.exists():
        saved=torch.load(checkpoint,weights_only=False,map_location='cpu')
        if saved['source_sha256']!=sha(Path(__file__)):raise ValueError('Probe checkpoint source changed')
        parent.load_state_dict(saved['state']);history=saved['history'];start=saved['generation']+1
        torch.set_rng_state(saved['torch_rng']);torch.cuda.set_rng_state_all(saved['cuda_rng'])
        for row in reversed(history):
            if row['accepted']:break
            stalls+=1
    for generation in range(start if stalls<4 else generations,generations):
        thermal();x,y=episodes(seed*10000+generation*2,128,scenario)
        child=copy.deepcopy(parent);optimizer=torch.optim.Adam(child.parameters(),lr=.015)
        for _ in range(12):
            weights,events=child(x);net,_,_=financial(weights,y,cost)
            # Financial head receives net outcome; event head separately learns
            # signed return and occurrence. No trade-count reward is present.
            loss=-net.mean()
            if events is not None:
                loss=loss+.01*nn.functional.mse_loss(events[...,0],y*100)
                loss=loss+.01*nn.functional.binary_cross_entropy_with_logits(events[...,1],(y.abs()>.004).float())
            optimizer.zero_grad();loss.backward();nn.utils.clip_grad_norm_(child.parameters(),1.);optimizer.step()
        random_child=copy.deepcopy(parent)
        with torch.no_grad():
            for p in random_child.parameters():p.add_(torch.randn_like(p)*.035)
        vx,vy=episodes(seed*10000+generation*2+1,128,scenario)
        before,before_metrics=score(parent,vx,vy,cost)
        candidate,candidate_metrics=score(child,vx,vy,cost)
        random_scores,random_metrics=score(random_child,vx,vy,cost)
        candidates=[('gradient_assisted',child,candidate,candidate_metrics),('random_mutation',random_child,random_scores,random_metrics)]
        winner=max(candidates,key=lambda row:float(row[2].mean()))
        delta=winner[2]-before
        accepted=float(delta.mean())>0
        if accepted:parent=winner[1];stalls=0
        else:stalls+=1
        history.append(dict(generation=generation,new_training_episode_seed=seed*10000+generation*2+1,
            parent=before_metrics,gradient_child=candidate_metrics,random_child=random_metrics,
            selected=winner[0] if accepted else 'parent',paired_improvement=float(delta.mean()),
            paired_se=float(delta.std(ddof=1)/np.sqrt(len(delta))),accepted=accepted))
        save_checkpoint(checkpoint,dict(state=parent.state_dict(),generation=generation,source_sha256=sha(Path(__file__)),
            history=history,kind=kind,scenario=scenario,seed=seed,torch_rng=torch.get_rng_state(),cuda_rng=torch.cuda.get_rng_state_all()))
        if stalls>=4:break
    # Neither this holdout nor its score participates in training or mutation.
    hx,hy=episodes(9000000+seed,512,scenario)
    final,final_metrics=score(parent,hx,hy,cost);base,base_metrics=score(initial,hx,hy,cost)
    delta=final-base
    return dict(kind=kind,scenario=scenario,seed=seed,history=history,initial=base_metrics,final=final_metrics,
        holdout_improvement=float(delta.mean()),holdout_improvement_95ci=[float(delta.mean()-1.96*delta.std(ddof=1)/np.sqrt(len(delta))),float(delta.mean()+1.96*delta.std(ddof=1)/np.sqrt(len(delta)))],
        cash_net=0.,synthetic_only=True,bybit_evidence=False,ready=False)


def run(output):
    output.mkdir(parents=True,exist_ok=True);torch.set_num_threads(2)
    plan=dict(source_sha256=sha(Path(__file__)),seeds=[17,29,43],scenarios=['clean','noisy_costs','noise'],
        kinds=['direct','experts'],generations=12,synthetic_only=True,ready=False)
    p=output/'plan.json'
    import json
    if p.exists() and json.loads(p.read_text())!=plan:raise ValueError('Probe plan changed')
    if not p.exists():atomic_json(p,plan)
    results=[]
    for scenario in plan['scenarios']:
        for kind in plan['kinds']:
            for seed in plan['seeds']:
                target=output/f'{kind}-{scenario}-{seed}.json'
                if target.exists():result=json.loads(target.read_text())
                else:
                    result=experiment(kind,scenario,seed,output);atomic_json(target,result)
                results.append(result)
    atomic_json(output/'result.json',dict(results=results,synthetic_only=True,bybit_evidence=False,ready=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.output)
