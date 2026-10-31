"""Frozen multi-day model/control validation through shared PAPER execution.

This stage cannot load final diagnostic arrays or promote a live candidate.
Only validation replay is selected; all costs/latencies remain declared scenarios.
"""
import argparse
from dataclasses import asdict,replace
import datetime as dt
import fcntl
import hashlib
from functools import partial
import json
from pathlib import Path
import numpy as np
import torch
from brain_archive_stream import sha
from brain_impulse_data import atomic_json
from brain_impulse_execution import ExecutionPolicy
from brain_impulse_replay import archive_events,replay
from brain_impulse_inference import SequenceSignals,neural_predictor
from brain_impulse_models import ImpulseNet
from brain_impulse_baselines import load as load_baseline
from brain_impulse_controls import signals
from brain_impulse_selection import MODELS,CONTROLS,select,freeze_policy
from brain_impulse_protocol import DAY

POLICIES={'base':ExecutionPolicy(),'stress':replace(ExecutionPolicy(),fee=.0008,slip=.0008,latency_ms=2000)}
CODE=('brain_impulse_evaluate.py','brain_impulse_replay.py','brain_impulse_execution.py',
      'brain_impulse_inference.py','brain_impulse_models.py','brain_impulse_baselines.py',
      'brain_impulse_controls.py','brain_archive_stream.py','brain_impulse_data.py',
      'brain_impulse_protocol.py','brain_impulse_selection.py','brain_impulse_dataset.py')


def freeze_execution(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    value=dict(policies={k:asdict(v) for k,v in POLICIES.items()},
        source={name:sha(Path(__file__).parent/name) for name in CODE},
        selection_sha256=freeze_policy(output),ready=False,independent_paper_evidence=False)
    target=output/'execution-policy.json'
    if target.exists() and json.loads(target.read_text())!=value:raise ValueError('Frozen execution policy/source changed')
    if not target.exists():atomic_json(target,value)
    return sha(target)


def predictors(output,fold):
    output=Path(output);result={};torch.set_num_threads(2)
    for kind in MODELS:
        folder=output/f'fold-{fold}'/kind;record=json.loads((folder/'result.json').read_text())
        if record['kind']!=kind or record['fold']!=fold or record['plan_sha256']!=sha(output/'training-plan.json'):
            raise ValueError('Model result identity mismatch')
        for name,h in record['artifacts'].items():
            if sha(folder/name)!=h:raise ValueError('Model artifact changed before replay')
        if kind in ('ridge','xgboost'):predict=load_baseline(kind,folder)
        else:
            net=ImpulseNet(kind);net.load_state_dict(torch.load(folder/'model.pt',weights_only=True,map_location='cpu'))
            with np.load(folder/'scaler.npz') as a:mean,std=a['mean'].copy(),a['std'].copy()
            predict=neural_predictor(net,mean,std,device='cpu')
        result[kind]=SequenceSignals(predict)
    result.update({kind:partial(signals,kind=kind) for kind in CONTROLS})
    return result


def plans_for_fold(campaign,start,end):
    if start%DAY or end%DAY or end<=start:raise ValueError('Require full calendar validation days')
    paths=[]
    for stamp in range(start,end,DAY):
        date=dt.datetime.fromtimestamp(stamp/1000,dt.timezone.utc).date().isoformat()
        path=Path(campaign)/date/'extraction-plan.json'
        value=json.loads(path.read_text())
        if any(s['day']!=date for s in value['sources']):raise ValueError('Archive day mismatch')
        paths.append(path)
    return paths


def all_events(paths):
    for path in paths:yield from archive_events(path)


def run(campaign,output):
    output=Path(output)
    with (output/'evaluation.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return _run(Path(campaign),output)


def _run(campaign,output):
    execution_sha256=freeze_execution(output)
    training=json.loads((output/'training-plan.json').read_text())
    if training['splits_sha256']!=sha(output/'split-plan.json') or training['selection_sha256']!=freeze_policy(output):
        raise ValueError('Training split or selection identity changed')
    for name,h in training['source'].items():
        if sha(Path(__file__).parent/name)!=h:raise ValueError('Training source changed before evaluation')
    summary=json.loads((output/'training-summary.json').read_text())
    if {(r['fold'],r['kind']) for r in summary['results']}!={(f,k) for f in range(2) for k in MODELS}:
        raise ValueError('Incomplete competitor family')
    for record in summary['results']:
        path=output/f"fold-{record['fold']}"/record['kind']/'result.json'
        if json.loads(path.read_text())!=record:raise ValueError('Model result differs from training summary')
    split=json.loads((output/'split-plan.json').read_text());folds=split['folds']
    if len(folds)!=2 or any(f['score_end_ms']>split['start_ms']+14*DAY for f in folds):
        raise ValueError('Validation attempted to access diagnostic interval')
    plan_paths=[plans_for_fold(campaign,f['early_end_ms'],f['score_end_ms']) for f in folds]
    metadata=campaign/'instrument-scenario.json'
    campaign_plan=campaign/'campaign-plan.json'
    if sha(metadata)!=json.loads(campaign_plan.read_text())['instrument_sha256']:
        raise ValueError('Instrument scenario differs from frozen campaign')
    for paths in plan_paths:
        for path in paths:
            if json.loads(path.read_text())['campaign_sha256']!=sha(campaign_plan):
                raise ValueError('Replay archive belongs to another campaign')
    identity=dict(execution_sha256=execution_sha256,training_summary_sha256=sha(output/'training-summary.json'),
        training_plan_sha256=sha(output/'training-plan.json'),split_sha256=sha(output/'split-plan.json'),
        metadata_sha256=sha(metadata),plans={str(p):sha(p) for paths in plan_paths for p in paths})
    ip=output/'evaluation-plan.json'
    if ip.exists() and json.loads(ip.read_text())!=identity:raise ValueError('Frozen evaluation inputs changed')
    if not ip.exists():atomic_json(ip,identity)
    inst=json.loads(metadata.read_text());inst=inst.get('instruments',inst)
    validation={kind:{name:[] for name in POLICIES} for kind in MODELS+CONTROLS}
    for number,(fold,paths) in enumerate(zip(folds,plan_paths)):
        for scenario,policy in POLICIES.items():
            if freeze_execution(output)!=execution_sha256:raise ValueError('Execution source mutation')
            target=output/f'validation-{number}-{scenario}.json'
            models=predictors(output,number)  # Verify models even when replay result is cached.
            if target.exists():
                saved=json.loads(target.read_text());result=saved['result']
                if saved['sha256']!=hashlib.sha256(json.dumps(result,sort_keys=True,allow_nan=False).encode()).hexdigest():
                    raise ValueError('Cached replay result changed')
                if result['evaluation_plan_sha256']!=sha(ip):raise ValueError('Replay result identity mismatch')
            else:
                atomic_json(output/'evaluation-status.json',dict(stage='replaying',fold=number,scenario=scenario,ready=False))
                result=replay(all_events(paths),models,inst,fold['early_end_ms'],fold['score_end_ms'],policy)
                result['evaluation_plan_sha256']=sha(ip)
                atomic_json(target,dict(result=result,sha256=hashlib.sha256(json.dumps(result,sort_keys=True,allow_nan=False).encode()).hexdigest()))
            for kind in validation:
                validation[kind][scenario].append(dict(days=list(range(fold['early_end_ms']//DAY,fold['score_end_ms']//DAY)),
                                                       report=result['reports'][kind]))
            del models
    # Inputs and policy are frozen before diagnostics are even considered.
    decision=select(validation);decision['evaluation_plan_sha256']=sha(ip)
    atomic_json(output/'validation-selection.json',decision)
    atomic_json(output/'evaluation-status.json',dict(stage='complete',selected_for_diagnostic=decision['selected_for_diagnostic'],ready=False))
    return decision


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--campaign',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.campaign,a.output)
