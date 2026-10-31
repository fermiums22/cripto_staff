"""Finite eight-fit neural competition stage, isolated from diagnostic data.

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

KINDS=('mlp','tcn','gru','moe')
CODE=('brain_impulse_train.py','brain_impulse_models.py','brain_impulse_splits.py',
      'brain_impulse_dataset.py','brain_impulse_data.py','brain_factory.py')


def run(campaign,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    with (output/'train.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return _train(campaign,output)


def _train(campaign,output):
    plan=freeze(campaign,output)
    source={n:sha(Path(__file__).parent/n) for n in CODE}
    identity=dict(splits_sha256=sha(output/'split-plan.json'),source=source,kinds=KINDS,
                  max_epochs=25,ready=False,stage='neural_training_only')
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
            net,mean,std=fit(kind,data,train,early,folder,sha(ip)+f':{number}:{kind}',25)
            forecast=predict(net,data,score,mean,std)
            path=folder/'validation-predictions.npz'
            with (folder/'predictions.part').open('wb') as f:
                np.savez(f,indices=score,signal_ms=data.times[score],predictions=forecast)
                f.flush();os.fsync(f.fileno())
            os.replace(folder/'predictions.part',path)
            record=dict(fold=number,kind=kind,plan_sha256=sha(ip),train_rows=len(train),
                early_rows=len(early),validation_rows=len(score),ready=False,
                artifacts={n:sha(folder/n) for n in ('model.pt','scaler.npz','checkpoint.pt','identity.json','validation-predictions.npz')})
            atomic_json(done,record);results.append(record)
            del net
    atomic_json(output/'training-summary.json',dict(results=results,ready=False,
        independent_paper_evidence=False,next_stage='Baseline competition and validation event-depth execution; no selection yet'))
    atomic_json(output/'status.json',dict(stage='training_complete',completed=len(results),ready=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--campaign',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    run(args.campaign,args.output)
