"""Bounded two-generation PPO/XGBoost arena; public history, no real orders."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import time
import numpy as np
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.env_checker import check_env
from xgboost import XGBRegressor
import agent
from evolution_env import TradingEnv,market_features


def save(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value),encoding='utf-8');tmp.replace(path)


def evaluate(env,policy):
    obs,_=env.reset()
    while True:
        obs,_,done,_,_=env.step(policy(obs,env))
        if done:break
    return env.report(),env.trades


def run(steps=32768):
    torch.set_num_threads(2)
    random.seed(42);np.random.seed(42);torch.manual_seed(42)
    run_id=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    root=agent.ARTIFACTS/'evolution'/run_id;root.mkdir(parents=True)
    status_path=agent.ARTIFACTS/'evolution_status.json'
    def status(stage,**kw):
        save(status_path,dict(run_id=run_id,stage=stage,updated_ms=int(time.time()*1000),**kw))
        print(stage,kw,flush=True)
    status('loading')
    path=agent.DATA/'evolution_history.json';raw=path.read_bytes();data=json.loads(raw)
    (root/'history.json').write_bytes(raw)
    for name in ('evolution_research.py','evolution_env.py','execution_research.py','agent.py','random_brackets.py'):
        (root/name).write_bytes(Path(name).read_bytes())
    x=market_features(data);n=len(x);train=n*2//3;cut=n*17//21
    if n<7*1440:raise ValueError('At least seven days required')
    mean=x[30:train].mean(axis=0);scale=x[30:train].std(axis=0);scale[scale<1e-8]=1
    fees=json.loads((agent.ARTIFACTS/'execution_fees.json').read_text());fee=float(fees['taker'])
    gpu=dict(torch_version=torch.__version__,ppo_device='cpu',xgboost_device='cuda')
    try:
        import pynvml
        pynvml.nvmlInit();handle=pynvml.nvmlDeviceGetHandleByIndex(0)
        gpu.update(name=pynvml.nvmlDeviceGetName(handle),
            total_mb=pynvml.nvmlDeviceGetMemoryInfo(handle).total//1048576,
            used_mb=pynvml.nvmlDeviceGetMemoryInfo(handle).used//1048576,
            utilization_pct=pynvml.nvmlDeviceGetUtilizationRates(handle).gpu,
            measured_ms=int(time.time()*1000))
    except Exception:
        gpu['telemetry']='unavailable; CUDA training checked through XGBoost config'
    config=dict(run_id=run_id,seed=42,steps_per_candidate=steps,history_sha256=hashlib.sha256(raw).hexdigest(),
        symbol=data['symbol'],bars=n,train_end_ms=data['trade'][train][0],test_start_ms=data['trade'][cut][0],
        start_ms=data['trade'][30][0],end_ms=data['trade'][-1][0]+60000,
        mean=mean.tolist(),scale=scale.tolist(),fees=fees,gpu=gpu,
        selection='validation return minus 0.5*max drawdown; final test never used for selection',
        execution=dict(leverage=1,allocation=.9,fee=fee,friction=.0006,risk_halt_equity=12))
    save(root/'config.json',config)
    (root/'dependencies.txt').write_text(subprocess.check_output([os.sys.executable,'-m','pip','freeze'],text=True))
    def env(a,b,**kw):return TradingEnv(data,x,mean,scale,a,b,fee=fee,**kw)
    check_env(env(30,train,episode_bars=512),warn=True)
    def score(r):return r['return_pct']-.5*r['max_drawdown_pct']
    candidates=[];policies={}
    # Small MLP PPO is faster on CPU; CUDA is used by the tree learner.
    for seed in (42,73):
        name=f'ppo_g0_s{seed}';status('training',generation=0,candidate=name,gpu=gpu)
        model=PPO('MlpPolicy',env(30,train,episode_bars=512),seed=seed,device='cpu',
            n_steps=512,batch_size=128,n_epochs=5,learning_rate=.0003,ent_coef=.01,
            policy_kwargs=dict(net_arch=[64,64]),verbose=0)
        initial=torch.cat([p.detach().flatten() for p in model.policy.parameters()]).clone()
        model.learn(total_timesteps=steps);model.save(root/name)
        delta=float(torch.linalg.vector_norm(torch.cat([p.detach().flatten() for p in model.policy.parameters()])-initial))
        if delta<=0:raise RuntimeError('PPO weights did not change')
        policy=lambda obs,e,m=model:int(m.predict(obs,deterministic=True)[0])
        validation,_=evaluate(env(train,cut),policy)
        candidates.append(dict(name=name,family='PPO',generation=0,seed=seed,parent=None,
            weight_delta_l2=delta,validation=validation,score=score(validation)))
        policies[name]=policy
    parent=max(candidates,key=lambda r:r['score'])['name']
    for j,(lr,entropy) in enumerate(((.0001,.003),(.0005,.02))):
        name=f'ppo_g1_m{j}';status('training',generation=1,candidate=name,parent=parent,gpu=gpu)
        model=PPO.load(root/parent,env=env(30,train,episode_bars=512),device='cpu')
        model.set_random_seed(100+j);model.learning_rate=lr;model.lr_schedule=lambda _:lr;model.ent_coef=entropy
        initial=torch.cat([p.detach().flatten() for p in model.policy.parameters()]).clone()
        model.learn(total_timesteps=steps,reset_num_timesteps=False);model.save(root/name)
        delta=float(torch.linalg.vector_norm(torch.cat([p.detach().flatten() for p in model.policy.parameters()])-initial))
        if delta<=0:raise RuntimeError('Continuation did not change PPO weights')
        policy=lambda obs,e,m=model:int(m.predict(obs,deterministic=True)[0])
        validation,_=evaluate(env(train,cut),policy)
        candidates.append(dict(name=name,family='PPO',generation=1,parent=parent,learning_rate=lr,
            entropy=entropy,weight_delta_l2=delta,validation=validation,score=score(validation)))
        policies[name]=policy
    status('training',candidate='XGBoost',generation=1,gpu=gpu)
    indices=np.arange(30,train-31)
    y=np.asarray([data['trade'][i+30][4]/data['trade'][i+1][1]-1 for i in indices])
    tree=XGBRegressor(n_estimators=200,max_depth=3,learning_rate=.03,subsample=.8,
        colsample_bytree=.8,random_state=42,device='cuda',tree_method='hist',n_jobs=2)
    tree.fit(x[indices],y);tree.save_model(root/'xgboost.json')
    if json.loads(tree.get_booster().save_config())['learner']['generic_param']['device']!='cuda:0':
        raise RuntimeError('XGBoost did not use CUDA')
    tree.set_params(device='cpu');prediction=tree.predict(x)
    for threshold in (.0032,.006):
        name=f'xgb_{threshold}'
        def policy(obs,e,t=threshold):
            p=float(prediction[e.i])
            if e.side and e.i-e.entry_index>=30:return 3
            if p>t:return 1
            if p<-t:return 2
            return 0
        validation,_=evaluate(env(train,cut),policy)
        candidates.append(dict(name=name,family='XGBoost',generation=0,parent=None,threshold=threshold,
            validation=validation,score=score(validation)))
        policies[name]=policy
    # Rules and cash are honest benchmarks with identical execution, not trained AI.
    def trend(obs,e):
        r=float(x[e.i,4]);return 1 if r>.0032 else 2 if r<-.0032 else 3
    def breakout(obs,e):
        bars=data['trade'];recent=bars[e.i-30:e.i];price=bars[e.i][4]
        if price>max(b[2] for b in recent):return 1
        if price<min(b[3] for b in recent):return 2
        return 3 if e.side and e.i-e.entry_index>=30 else 0
    for name,policy in [('cash',lambda obs,e:0),('trend',trend),('breakout',breakout)]:
        validation,_=evaluate(env(train,cut),policy)
        candidates.append(dict(name=name,family='baseline',generation=0,parent=None,
            validation=validation,score=score(validation)))
        policies[name]=policy
    # Cash wins exact ties: inactivity is not evidence of a learned advantage.
    selected=max(candidates,key=lambda r:(r['score'],r['name']=='cash'))['name']
    save(root/'selection.json',dict(selected=selected,candidates=candidates))
    status('final_test',generation=1,selected=selected,gpu=gpu)
    # Freeze every candidate above before accessing final-period performance.
    for candidate in candidates:
        name=candidate['name'];policy=policies[name]
        candidate['test'],records=evaluate(env(cut,n),policy)
        candidate['stress'],_=evaluate(env(cut,n,friction=.0011),policy)
        candidate['periods']=[]
        for a,b in ((cut,(cut+n)//2),((cut+n)//2,n)):
            r,_=evaluate(env(a,b),policy);candidate['periods'].append(r)
        with (root/(name+'.csv')).open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(records[0]) if records else ['net'])
            writer.writeheader();writer.writerows(records)
        assert abs(candidate['test']['capital']-(15+sum(t['net'] for t in records)))<1e-7
    # One continuous test trajectory per risk budget; no resets between test days.
    challenge=[]
    for allocation in (.5,.9):
        r,_=evaluate(env(cut,n,allocation=allocation),policies[selected])
        challenge.append(dict(selected=selected,allocation=allocation,leverage=1,target=40000,
            achieved=r['capital']>=40000,ruin_probability=None,**r))
    result=dict(**config,selected=selected,candidates=candidates,challenge=challenge,auto_promoted=False,
        limitations=['Minute bars, not tick/order-book replay; taker fills only in this phase.',
            'Previously inspected overlapping history is not an independent unseen market sample.',
            'Two test subperiods do not establish ruin probability or stable profitability.',
            'Liquidation is a conservative mark-OHLC proxy; no leveraged challenge in this phase.',
            'Qwen/Nika remains paused; no generated code, no automatic promotion.'])
    save(root/'report.json',result);save(agent.ARTIFACTS/'evolution_research.json',result)
    status('complete',generation=1,selected=selected,gpu=gpu,report=str(root/'report.json'))
    print(json.dumps({r['name']:r['test']['return_pct'] for r in candidates}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--steps',type=int,default=32768)
    args=parser.parse_args()
    if args.steps<512:parser.error('steps must be at least 512')
    try:run(args.steps)
    except Exception as exc:
        save(agent.ARTIFACTS/'evolution_status.json',dict(stage='failed',error=type(exc).__name__,updated_ms=int(time.time()*1000)))
        raise
