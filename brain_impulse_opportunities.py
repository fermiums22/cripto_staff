"""Bounded TRAIN-only impulse opportunity audit; not a tradable oracle backtest.

Thresholds use features from Oct2-3 only. Fixed hypotheses are scored once on
Oct4-7 training episodes. No diagnostic/final/prospective period is accessed.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from brain_archive_stream import sha
from brain_impulse_data import FEATURES,atomic_json
from brain_impulse_dataset import load,ASSETS,HORIZONS


def read_day(campaign,day):
    directory=campaign/day/'dataset';meta,a=load(directory)
    for name,h in meta['artifact_hashes'].items():
        if sha(directory/name)!=h:raise ValueError('Dataset hash changed')
    order=np.argsort(a['signal_ms'],kind='stable')
    return dict(x=np.asarray(a['features'][a['windows'][order,-1]]),
        y=np.asarray(a['targets'][order]),t=np.asarray(a['signal_ms'][order]),
        symbols=np.asarray(a['symbols'][order]),identity=sha(directory/'dataset.json'))


def thresholds(x):
    return dict(lead=float(np.quantile(np.abs((x[:,21]+x[:,22])/2),.95)),
        acceleration=float(np.quantile(np.abs(x[:,4]),.95)),
        volume=float(np.quantile(x[:,15],.9)),flow=float(np.quantile(np.abs(x[:,13]),.95)),
        spread=float(np.quantile(x[:,12],.5)),momentum=float(np.quantile(np.abs(x[:,1]),.9)))


def masks(x,side,cut):
    return dict(leadlag=(side*(x[:,21]+x[:,22])/2>cut['lead'])&(side*x[:,13]>0)&(side*x[:,7]>0),
        acceleration=(side*x[:,4]>cut['acceleration'])&(x[:,15]>cut['volume'])&(side*x[:,0]>0),
        flow=(side*x[:,13]>cut['flow'])&(side*x[:,8]>0)&(side*x[:,0]>0)&(x[:,12]<=cut['spread']),
        momentum=side*x[:,1]>cut['momentum'])


def thin(times,mask,gap=180000):
    chosen=[];previous=-2**63
    for i in np.flatnonzero(mask):
        if int(times[i])-previous>=gap:chosen.append(i);previous=int(times[i])
    return np.asarray(chosen,dtype='int64')


def stats(values):
    return dict(n=len(values),mean_net=float(np.mean(values)) if len(values) else None,
        positive_fraction=float(np.mean(values>0)) if len(values) else None,
        beyond_10bp_fraction=float(np.mean(values>.001)) if len(values) else None,
        quantiles=np.quantile(values,[.01,.5,.9,.99]).tolist() if len(values) else None)


def run(campaign,output):
    output.mkdir(parents=True,exist_ok=True)
    fit_days=['2026-10-02','2026-10-03'];score_days=[f'2026-10-{i:02d}' for i in range(4,8)]
    fitting=[read_day(campaign,day) for day in fit_days];cut=thresholds(np.concatenate([d['x'] for d in fitting]))
    plan=dict(fit_days=fit_days,score_days=score_days,thresholds=cut,feature_names=list(FEATURES),
        source_sha256=sha(Path(__file__)),fit_identities=[d['identity'] for d in fitting],
        thinning_ms=180000,scope='TRAIN_ONLY',labels='fixed-horizon net proxy, NOT stopped portfolio execution',ready=False)
    p=output/'plan.json'
    if p.exists() and json.loads(p.read_text())!=plan:raise ValueError('Opportunity plan changed')
    if not p.exists():atomic_json(p,plan)
    del fitting
    rows=[];density=[];identities={}
    for day in score_days:
        d=read_day(campaign,day);identities[day]=d['identity']
        for asset,symbol in enumerate(ASSETS):
            asset_mask=d['symbols']==asset
            for h,horizon in enumerate(HORIZONS):
                density.append(dict(day=day,symbol=symbol,horizon_ms=horizon,
                    observed_targets=int(asset_mask.sum()),
                    hindsight_positive=float(np.mean(np.max(d['y'][asset_mask,2*h:2*h+2],axis=1)>0)),
                    hindsight_above_10bp=float(np.mean(np.max(d['y'][asset_mask,2*h:2*h+2],axis=1)>.001)),
                    tradable_claim=False))
            for side,j in ((1,0),(-1,1)):
                for name,mask in masks(d['x'],side,cut).items():
                    ids=thin(d['t'],mask&asset_mask)
                    for h,horizon in enumerate(HORIZONS):
                        rows.append(dict(day=day,symbol=symbol,side=side,hypothesis=name,horizon_ms=horizon,
                            **stats(d['y'][ids,2*h+j])))
    atomic_json(output/'result.json',dict(plan_sha256=sha(p),score_identities=identities,rows=rows,
        opportunity_density=density,ready=False,independent_evidence=False,
        limitations=['known training history only','hindsight opportunity rate is not realizable strategy PnL',
                    'fixed hypotheses still constitute multiple comparisons','no final-test or paper qualification']))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--campaign',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.campaign,a.output)
