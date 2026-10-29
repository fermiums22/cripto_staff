"""Attribution of a frozen historical result, without fitting or selecting models."""
import csv
import gzip
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from xgboost import XGBRegressor
import agent
from portfolio_market import write
from portfolio_research import build_features
from portfolio_sim import simulate,fill


def trade_key(t):return (t['symbol'],t['entry_ms'],t['side'])


def summarize(records):
    result={}
    for t in records:
        r=result.setdefault(t['symbol'],dict(trades=0,wins=0,gross=0.,fees=0.,funding=0.,net=0.))
        r['trades']+=1;r['wins']+=t['net']>0
        for k in ('gross','fees','funding','net'):r[k]+=t[k]
    return result


def reprice(records,market,friction,fee):
    """Fixed quantities and timestamps, diagnostic only: no reallocation/liquidation."""
    net=0.;friction_cost=0.;fees=0.;reference_gross=0.
    for t in records:
        d=market[t['symbol']];first=d['trade'][0][0]
        a=(t['entry_ms']-first)//900000
        b=(t['exit_ms']-first-(900000 if t['reason']=='boundary' else 0))//900000
        entry=d['trade'][a][1]
        exit_price=d['trade'][b][4 if t['reason']=='boundary' else 1]
        if t['reason']=='liquidation_proxy':raise ValueError('Fixed-path liquidation repricing unsupported')
        actual_entry=fill(entry,t['side'],friction,d['instrument'])
        actual_exit=fill(exit_price,-t['side'],friction,d['instrument'])
        raw=t['qty']*t['side']*(exit_price-entry)
        gross=t['qty']*t['side']*(actual_exit-actual_entry)
        commission=t['qty']*(actual_entry+actual_exit)*fee
        reference_gross+=raw;friction_cost+=raw-gross;fees+=commission;net+=gross-commission+t['funding']
    return dict(net=net,capital=15+net,reference_gross=reference_gross,friction_cost=friction_cost,fees=fees)


def run():
    report=json.loads((agent.ARTIFACTS/'portfolio_research.json').read_text())
    root=agent.ARTIFACTS/'portfolio'/report['run'];config=json.loads((root/'config.json').read_text())
    candidate=next(c for c in report['candidates'] if c['name']==report['selected'])
    if candidate['family']!='xgb':raise ValueError('This audit supports the frozen XGBoost selection')
    market={}
    for s,h in config['history_hashes'].items():
        raw=(root/(s+'.json.gz')).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=h:raise ValueError('History hash mismatch')
        market[s]=json.loads(gzip.decompress(raw))
    x=build_features(market);tree=XGBRegressor();tree.load_model(root/'xgboost.json');tree.set_params(device='cpu')
    predictions={s:tree.predict(v) for s,v in x.items()};n=len(next(iter(x.values())))
    args=dict(mode=candidate['mode'],leverage=candidate['leverage'],fee=report['fee_assumption'])
    base=simulate(market,predictions,n*2//3,n,**args)
    stress=simulate(market,predictions,n*2//3,n,friction=.0016,**args)
    for label,result in [('test',base),('stress',stress)]:
        for metric in ('capital','fees','trades','max_drawdown_pct'):
            if abs(result[metric]-candidate[label][metric])>1e-8:raise ValueError('Frozen replay changed '+metric)
    records=base['records'];ranked=sorted(records,key=lambda t:t['net'],reverse=True)
    fixed_base=reprice(records,market,.0006,args['fee']);fixed_stress=reprice(records,market,.0016,args['fee'])
    if abs(fixed_base['capital']-base['capital'])>1e-8:raise ValueError('Cost bridge mismatch')
    a={trade_key(t):t for t in records};b={trade_key(t):t for t in stress['records']}
    common=set(a)&set(b)
    sensitivities={}
    for hours in (2,8,16):
        result=simulate(market,predictions,n*2//3,n,hold_bars=hours*4,**args)
        sensitivities[str(hours)+'h']={k:result[k] for k in ('capital','return_pct','trades','max_drawdown_pct')}
    without_q=dict(predictions);without_q['QUSDT']=np.zeros(n)
    result=simulate(market,without_q,n*2//3,n,**args)
    sensitivities['without_Q']={k:result[k] for k in ('capital','return_pct','trades','max_drawdown_pct')}
    winners=[t['net'] for t in records if t['net']>0];losers=[t['net'] for t in records if t['net']<=0]
    curve=base['curve'];peak=15.;peak_ms=curve[0][0];close_dd=dict(pct=0)
    for ts,value in curve:
        if value>peak:peak=value;peak_ms=ts
        decline=(1-value/peak)*100
        if decline>close_dd['pct']:close_dd=dict(pct=decline,peak_ms=peak_ms,trough_ms=ts,peak=peak,equity=value)
    out=dict(source_run=report['run'],selected=report['selected'],created_ms=int(time.time()*1000),
        base={k:base[k] for k in ('capital','return_pct','fees','funding','trades','wins','max_drawdown_pct','drawdown_event','curve')},
        stress={k:stress[k] for k in ('capital','return_pct','fees','funding','trades','max_drawdown_pct','curve')},
        coins=summarize(records),stress_coins=summarize(stress['records']),top_trades=ranked[:10],worst_trades=ranked[-10:][::-1],sensitivity=sensitivities,
        profit_factor=sum(winners)/-sum(losers) if sum(losers) else None,
        mean_win=float(np.mean(winners)) if winners else 0,mean_loss=-float(np.mean(losers)) if losers else 0,
        concentration=[dict(remove_best=k,arithmetic_net=base['capital']-15-sum(t['net'] for t in ranked[:k])) for k in (1,3,5,10)],
        fixed_base=fixed_base,fixed_stress=fixed_stress,
        cost_bridge=dict(direct_extra_cost=fixed_base['net']-fixed_stress['net'],
            changed_path_effect=stress['capital']-fixed_stress['capital'],
            common_entries=len(common),base_only=len(set(a)-set(b)),stress_only=len(set(b)-set(a)),
            changed_quantity=sum(abs(a[k]['qty']-b[k]['qty'])>1e-10 for k in common),
            changed_exit=sum(a[k]['exit_ms']!=b[k]['exit_ms'] for k in common)),
        sampled_close_drawdown=close_dd,
        notes=['Concentration subtracts recorded profits; it is not a feasible counterfactual replay.',
            'Fixed-path stress holds sizes and times unchanged; full stress resizes and reallocates.',
            '35.9% drawdown uses simultaneous adverse mark extremes inside a bar, a conservative envelope.',
            'Universe is still current survivors. Attribution does not remove this selection bias.',
            'Holding and without-Q replays are post-hoc sensitivity diagnostics, not new holdout selection.',
            'No retraining, parameter tuning, new strategies or real orders.'])
    write(root/'audit.json',out);write(agent.ARTIFACTS/'portfolio_audit.json',out)
    with (root/'stress_trades.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(stress['records'][0]));w.writeheader();w.writerows(stress['records'])
    print(json.dumps({k:out[k] for k in ('coins','concentration','cost_bridge','fixed_base','fixed_stress','sampled_close_drawdown')}))


if __name__=='__main__':run()
