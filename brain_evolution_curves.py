"""Standalone plots of observed generations and synthetic learning, not promotion."""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from brain_impulse_data import atomic_json


def render(lab,probe,output):
    output.mkdir(parents=True,exist_ok=True);history=[]
    for p in sorted(lab.glob('train-*/result.json')):
        r=json.loads(p.read_text());active=[v for v in r['agents'].values() if v['trades']>0]
        values=[v['net_return'] for v in active]
        history.append(dict(generation=r['generation'],days=r['days'],best=max(values) if values else None,
            median=float(np.median(values)) if values else None,cash=0.,active=len(active),
            trades=sum(v['trades'] for v in active),inactive=len(r['agents'])-len(active),
            families=len({v['family'] for v in r['population']}),
            behaviors=len({(v['architecture'],v.get('leverage'),v.get('hold_ms'),v.get('symbol')) for v in r['population']})))
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
    if history:
        g=[r['generation'] for r in history]
        for key in ('best','median','cash'):axes[0].plot(g,[100*r[key] for r in history],marker='o',label=key)
        axes[0].set_title('Recorded market: different dates per generation\nNot a causal improvement estimate')
        axes[0].set_xlabel('Generation');axes[0].set_ylabel('Mean episode net return (%)');axes[0].legend();axes[0].grid(alpha=.2)
    result=json.loads((probe/'result.json').read_text())
    for kind in ('direct','experts'):
        rows=[r for r in result['results'] if r['scenario']=='noisy_costs' and r['kind']==kind]
        for generation in range(12):
            paired=[r['history'][generation] for r in rows if len(r['history'])>generation]
            if not paired:continue
            value=np.mean([max(x['parent']['net'],x['gradient_child']['net'],x['random_child']['net']) for x in paired])
            axes[1].scatter(generation,100*value,color='tab:blue' if kind=='direct' else 'tab:orange',label=kind if generation==0 else None)
    axes[1].axhline(0,color='black',ls='--',label='CASH');axes[1].set_title('Synthetic signal + noise + costs\nFresh training episodes; NOT Bybit evidence')
    axes[1].set_xlabel('Generation');axes[1].set_ylabel('Mean episode net return (%)');axes[1].legend();axes[1].grid(alpha=.2)
    fig.savefig(output/'learning-curves.png',dpi=160);fig.savefig(output/'learning-curves.svg');plt.close(fig)
    atomic_json(output/'generation-metrics.json',dict(history=history,ready=False,independent_evidence=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--lab',type=Path,required=True);p.add_argument('--probe',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();render(a.lab,a.probe,a.output)
