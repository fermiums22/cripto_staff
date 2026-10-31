"""Finite twelve-fit competition training stage, isolated from diagnostic data.

Scores alone cannot promote a model. Validation event-depth execution and baseline
comparison must select a candidate before the diagnostic/future stages are opened.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import numpy as np
from brain_archive_stream import sha
from brain_impulse_data import atomic_json
from brain_impulse_models import Frames,fit,predict
from brain_impulse_splits import freeze,indices
from brain_impulse_baselines import fit as fit_baseline

KINDS=('ridge','xgboost','mlp','tcn','gru','moe')
CODE=('brain_impulse_train.py','brain_impulse_models.py','brain_impulse_splits.py',
      'brain_impulse_dataset.py','brain_impulse_data.py','brain_factory.py','brain_impulse_baselines.py')


def run(campaign,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    with (output/'train.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return _train(campaign,output)


def _train(campaign,output):
    plan=freeze(campaign,output)
    source={n:sha(Path(__file__).parent/n) for n in CODE}
    identity=dict(splits_sha256=sha(output/'split-plan.json'),source=source,kinds=KINDS,
                  max_epochs=25,ready=False,stage='competition_training_only')
    identity=json.loads(json.dumps(identity));ip=output/'training-plan.json'
    if ip.exists() and json.loads(ip.read_text())!=identity:raise ValueError('Frozen training plan changed')
    if not ip.exists():atomic_json(ip,identity)
    # Deliberately never instantiate a Frames loader for the final seven days.
    data=Frames([d['dataset'] for d in plan['development']]);results=[]
    for number,fold in enumerate(plan['folds']):
        train,early,score=indices(data,plan['start_ms'],fold['train_end_ms'],fold['early_end_ms'],fold['score_end_ms'])
        for kind in KINDS:
            if source!={n:sha(Path(__file__).parent/n) for n in CODE}:raise ValueError('Training source changed')
            folder=output/f'fold-{number}'/kind;folder.mkdir(parents=True,exist_ok=True)
            done=folder/'result.json'
            if done.exists():
                record=json.loads(done.read_text())
                if record['plan_sha256']!=sha(ip):raise ValueError('Result plan mismatch')
                for name,h in record['artifacts'].items():
                    if sha(folder/name)!=h:raise ValueError('Training artifact changed')
                results.append(record);continue
            atomic_json(output/'status.json',dict(stage='training',fold=number,kind=kind,completed=len(results),ready=False))
            experiment_id=sha(ip)+f':{number}:{kind}'
            if kind in ('ridge','xgboost'):
                predictor=fit_baseline(kind,data,train,folder,experiment_id)
                parts=[]
                for offset in range(0,len(score),1024):
                    x,_=data.batch(score[offset:offset+1024]);parts.append(predictor(x))
                forecast=np.concatenate(parts)
                artifacts=list(json.loads((folder/'baseline-result.json').read_text())['artifacts'])
                artifacts+=['baseline-result.json','baseline-identity.json']
                del predictor
            else:
                net,mean,std=fit(kind,data,train,early,folder,experiment_id,25)
                forecast=predict(net,data,score,mean,std)
                artifacts=['model.pt','scaler.npz','checkpoint.pt','identity.json']
                del net
            if forecast.shape!=(len(score),8) or not np.isfinite(forecast).all():raise ValueError('Invalid validation predictions')
            path=folder/'validation-predictions.npz'
            with (folder/'predictions.part').open('wb') as f:
                np.savez(f,indices=score,signal_ms=data.times[score],predictions=forecast)
                f.flush();os.fsync(f.fileno())
            os.replace(folder/'predictions.part',path)
            record=dict(fold=number,kind=kind,plan_sha256=sha(ip),train_rows=len(train),
                early_rows=len(early),validation_rows=len(score),ready=False,
                artifacts={n:sha(folder/n) for n in artifacts+['validation-predictions.npz']})
            atomic_json(done,record);results.append(record)
    atomic_json(output/'training-summary.json',dict(results=results,ready=False,
        independent_paper_evidence=False,next_stage='Validation event-depth execution and comparison to fixed trading rules; no selection yet'))
    atomic_json(output/'status.json',dict(stage='training_complete',completed=len(results),ready=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--campaign',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    run(args.campaign,args.output)
