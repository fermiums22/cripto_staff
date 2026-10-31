"""Matched parent/offspring comparisons on the SAME fresh training episodes."""
import argparse
import json
from pathlib import Path
import torch
from brain_impulse_data import atomic_json


def same_policy(a,b):
    ignored={'id','parent','generation','weights'}
    if {k:v for k,v in a.items() if k not in ignored}!={k:v for k,v in b.items() if k not in ignored}:return False
    wa,wb=a.get('weights',{}),b.get('weights',{})
    return wa.keys()==wb.keys() and all(torch.equal(wa[k],wb[k]) for k in wa)


def audit(lab,output):
    rows=[];unmatched=[]
    for generation in (1,2):
        folder=lab/f'train-{generation}'
        if not (folder/'result.json').exists():continue
        old=torch.load(lab/f'train-{generation-1}/population.pt',weights_only=False,map_location='cpu')['population']
        pop=torch.load(folder/'population.pt',weights_only=False,map_location='cpu')['population']
        parents={p['id']:p for p in old};scores=json.loads((folder/'result.json').read_text())['agents']
        for child in pop:
            parent=parents.get(child.get('parent'))
            if parent is None or same_policy(parent,child):continue
            controls=[p for p in pop if same_policy(parent,p)]
            if not controls:unmatched.append(dict(generation=generation,child=child['id'],reason='parent not replayed unchanged on this period'));continue
            control=controls[0];a=scores[control['id']];b=scores[child['id']]
            changes={k:dict(parent=parent.get(k),child=child.get(k)) for k in ('gain','fraction','leverage','hold_ms','stop','symbol','architecture') if parent.get(k)!=child.get(k)}
            if child.get('weights'):changes['weights']='mutated'
            rows.append(dict(generation=generation,child=child['id'],control=control['id'],changes=changes,
                net_return_delta=b['net_return']-a['net_return'],fees_delta=b['fees']-a['fees'],
                trades_delta=b['trades']-a['trades'],drawdown_delta=b['max_drawdown']-a['max_drawdown'],
                per_episode_delta=[x-y for x,y in zip(b['episode_returns'],a['episode_returns'])],
                child_net_return=b['net_return'],child_trades=b['trades'],
                improved_both_episodes=all(x>y for x,y in zip(b['episode_returns'],a['episode_returns'])),
                active_improvement=b['trades']>0 and a['trades']>0 and all(x>y for x,y in zip(b['episode_returns'],a['episode_returns'])),
                no_trade_child=b['trades']==0,
                evidence_issues=sorted(set(a['evidence_issues']+b['evidence_issues']))))
    atomic_json(output,dict(comparisons=rows,unmatched=unmatched,ready=False,independent_evidence=False,
        caution='Two fresh training episodes per comparison; multiple mutations and comparisons, not statistical proof of alpha'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--lab',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();audit(a.lab,a.output)
