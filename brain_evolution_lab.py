"""Bounded evolutionary action lab. Training feedback never authorizes PAPER entry.

Three generations use disjoint, sequential training episodes. Development
validation is read once for the final frozen population and cannot breed children.
The old reserved diagnostic and prospective periods remain unopened here.
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
from brain_archive_stream import sha
from brain_factory import thermal,save_checkpoint
from brain_impulse_data import atomic_json
from brain_impulse_dataset import ASSETS
from brain_evolution_env import ExplorationAccount
from brain_evolution_policy import population,outputs,action,evolve,fitness
from brain_evolution_tape import prepare,load

FILES=('brain_evolution_lab.py','brain_evolution_env.py','brain_evolution_policy.py','brain_evolution_tape.py',
       'brain_impulse_execution.py','brain_impulse_replay.py','brain_impulse_data.py','brain_archive_stream.py','brain_factory.py')


def replay(tape,candidates,instruments,mean,std,device='cuda'):
    predictions={c['id']:outputs(c,tape['fx'],mean,std,device) for c in candidates}
    accounts={c['id']:ExplorationAccount(instruments) for c in candidates}
    cache={};bi=fi=0;due=None;next_decision=0
    end=int(max(tape['bt'][-1],tape['ft'][-1]));closing=end-190000
    while bi<len(tape['bt']) or fi<len(tape['ft']):
        bt=int(tape['bt'][bi]) if bi<len(tape['bt']) else 2**63-1
        ft=int(tape['ft'][fi]) if fi<len(tape['ft']) else 2**63-1
        now=min(bt,ft)
        if bt<=ft:
            symbol=ASSETS[int(tape['bs'][bi])];levels=tape['depth'][bi]
            book=dict(ts=now,symbol=symbol,bids=[(float(v[0]),float(v[1])) for v in levels[0] if v[1]>0],asks=[(float(v[0]),float(v[1])) for v in levels[1] if v[1]>0])
            for account in accounts.values():
                if ((account.position and account.position['symbol']==symbol) or
                    (account.pending and account.pending.get('symbol')==symbol)):
                    account.book(book)
            bi+=1
        else:
            symbol=int(tape['fs'][fi]);cache[symbol]=(now,fi);fi+=1
            if due is None and now>=next_decision:due=now+500
        if due is None or now<due:continue
        for c in candidates:
            account=accounts[c['id']]
            if now>=closing:
                if account.pending and account.pending['kind']!='CLOSE':account.pending=None
                if account.position and not account.pending:account.act(dict(kind='CLOSE'),now)
                continue
            if account.pending or account.bankrupt:continue
            options=[]
            for symbol,(observed,index) in cache.items():
                if not 0<=now-observed<=1500:continue
                if account.position and account.position['symbol']!=ASSETS[symbol]:continue
                v=predictions[c['id']][index];a=action(c,v,symbol,account.position,now)
                a['symbol']=ASSETS[symbol]
                options.append((abs(float(v[0])) if a['kind'] in ('BUY','SELL','CLOSE') else -1,symbol,a))
            if options:
                options.sort(key=lambda v:(-v[0],v[1]));account.act(options[0][2],now)
        next_decision=now+4500;due=None
    return {name:account.report() for name,account in accounts.items()}


def aggregate(episodes):
    result={}
    for name in episodes[0]:
        rows=[e[name] for e in episodes]
        result[name]=dict(net_return=float(np.mean([x['net_return'] for x in rows])),
            net_pnl=sum(x['net_pnl'] for x in rows),max_drawdown=max(x['max_drawdown'] for x in rows),
            fees=sum(x['fees'] for x in rows),trades=sum(x['trades'] for x in rows),
            liquidations=sum(x['liquidations'] for x in rows),
            evidence_issues=sorted({i for x in rows for i in x['evidence_issues']}),
            episode_returns=[x['net_return'] for x in rows],ready=False)
    return result


def store_json_gz(path,value):
    tmp=path.with_suffix('.part')
    with tmp.open('wb') as raw:
        with gzip.GzipFile(fileobj=raw,mode='wb') as f:f.write(json.dumps(value,allow_nan=False).encode())
        raw.flush();os.fsync(raw.fileno())
    os.replace(tmp,path)


def freeze(output,campaign):
    # Dates are fixed before any lab financial outcomes are computed.
    plan=dict(mode='EXPLORATION',training_days=[['2026-10-02','2026-10-03'],['2026-10-04','2026-10-05'],['2026-10-06','2026-10-07']],
        development_validation=['2026-10-08','2026-10-09'],generations=3,seed=7301,
        final_test_access=False,independent_evidence=False,ready=False,
        method='financial-fitness evolutionary policy search, gradient-free; CUDA policy evaluation',
        source={n:sha(Path(__file__).parent/n) for n in FILES},
        campaign_sha256=sha(campaign/'campaign-plan.json'),instruments_sha256=sha(campaign/'instrument-scenario.json'))
    for day in sum(plan['training_days'],[])+plan['development_validation']:
        plan.setdefault('inputs',{})[day]=sha(campaign/day/'extraction-plan.json')
    p=output/'plan.json'
    if p.exists() and json.loads(p.read_text())!=plan:raise ValueError('Frozen lab plan changed')
    if not p.exists():atomic_json(p,plan)
    snapshot=output/'source';snapshot.mkdir(exist_ok=True)
    for name,h in plan['source'].items():
        target=snapshot/name
        if not target.exists():target.write_bytes((Path(__file__).parent/name).read_bytes())
        if sha(target)!=h:raise ValueError('Frozen lab source snapshot changed')
    return plan


def run(campaign,output):
    output.mkdir(parents=True,exist_ok=True)
    with (output/'worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        plan=freeze(output,campaign)
        if (output/'result.json').exists():
            done=json.loads((output/'result.json').read_text())
            for name,h in done['artifacts'].items():
                if sha(output/name)!=h:raise ValueError('Completed lab artifact changed')
            return done
        if not torch.cuda.is_available():raise RuntimeError('RTX/CUDA required for actual policy population evaluation')
        torch.set_num_threads(2);torch.cuda.set_per_process_memory_fraction(.35)
        instruments=json.loads((campaign/'instrument-scenario.json').read_text());instruments=instruments.get('instruments',instruments)
        pop=population(plan['seed']);mean=std=None;history=[]
        phases=[('train',i,days) for i,days in enumerate(plan['training_days'])]+[('validation',2,plan['development_validation'])]
        for phase,generation,days in phases:
            folder=output/f'{phase}-{generation}';folder.mkdir(exist_ok=True)
            checkpoint=folder/'population.pt'
            if checkpoint.exists():
                saved=torch.load(checkpoint,map_location='cpu',weights_only=False)
                if saved['plan_sha256']!=sha(output/'plan.json'):raise ValueError('Population plan mismatch')
                pop=saved['population'];mean=saved['mean'];std=saved['std']
            episodes=[]
            for day in days:
                thermal()
                atomic_json(output/'status.json',dict(phase=phase,generation=generation,day=day,stage='preparing_tape',ready=False))
                tape=load(prepare(campaign/day/'extraction-plan.json',output/'tapes'/day))
                if mean is None:
                    mean=tape['fx'].mean(0);std=np.maximum(tape['fx'].std(0),1e-6)
                if not checkpoint.exists():save_checkpoint(checkpoint,dict(plan_sha256=sha(output/'plan.json'),population=pop,mean=mean,std=std))
                target=folder/(day+'.json.gz');digest=folder/(day+'.sha256')
                if target.exists() and digest.exists():
                    if sha(target)!=digest.read_text().strip():raise ValueError('Episode evidence changed')
                    with gzip.open(target,'rt') as f:reports=json.load(f)
                else:
                    atomic_json(output/'status.json',dict(phase=phase,generation=generation,day=day,stage='virtual_trading',ready=False))
                    reports=replay(tape,pop,instruments,mean,std)
                    store_json_gz(target,reports);digest.write_text(sha(target))
                episodes.append({name:{k:v for k,v in row.items() if k not in ('actions','trades_detail')} for name,row in reports.items()})
                del tape,reports
            scores=aggregate(episodes)
            info=dict(phase=phase,generation=generation,days=days,agents=scores,
                population=[{k:v for k,v in c.items() if k!='weights'} for c in pop],
                neural_policies=sum(c['family']=='neural' for c in pop),
                newly_mutated_neural_policies=0 if generation==0 or phase=='validation' else 3,
                gradient_fits=0,optimization='financial-fitness evolutionary selection and parameter mutation',
                ready=False,independent_evidence=False)
            atomic_json(folder/'result.json',info);history.append(info)
            if phase=='train' and generation<2:pop=evolve(pop,scores,generation+1,plan['seed'])
        artifacts={str(p.relative_to(output)):sha(p) for p in output.glob('*-*/*') if p.is_file() and p.suffix in ('.pt','.json','.gz')}
        atomic_json(output/'result.json',dict(history=history,ready=False,artifacts=artifacts,
            next_step='Freeze a candidate and protocol before fresh independent evaluation; no live promotion',
            limitations=['one-second sampled execution','scenario liquidation and historical instrument rules',
                         'no exact funding or maker queue','historical development validation is not independent test']))
        atomic_json(output/'status.json',dict(stage='completed_exploration',ready=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--campaign',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.campaign,a.output)
