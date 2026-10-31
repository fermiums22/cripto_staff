"""Fixed ridge and CUDA boosted-tree competitors, fitted to training rows only.

Both use last/mean/change of the same causal eight-observation input. At most
100,000 evenly spaced chronological training examples bound memory and runtime.
No hyperparameter search or final diagnostic data are accepted by this module.
"""
import hashlib
import json
import os
from pathlib import Path
import numpy as np
from brain_archive_stream import sha
from brain_impulse_data import atomic_json
from brain_factory import thermal


def features(x):
    x=np.asarray(x,dtype='float32')
    if x.ndim!=3 or x.shape[1:]!=(8,30) or not np.isfinite(x).all():raise ValueError('Invalid sequence features')
    return np.concatenate((x[:,-1],x.mean(1),x[:,-1]-x[:,0]),axis=1)


def training_rows(data,ids):
    ids=np.asarray(ids,dtype='int64')
    if not len(ids) or np.any(np.diff(data.times[ids])<0):raise ValueError('Training indices must be chronological')
    chosen=ids[np.linspace(0,len(ids)-1,min(100000,len(ids)),dtype='int64')]
    xs=[];ys=[]
    for offset in range(0,len(chosen),2048):
        x,y=data.batch(chosen[offset:offset+2048]);xs.append(features(x));ys.append(y)
    x,y=np.concatenate(xs),np.concatenate(ys)
    if y.shape!=(len(x),8) or not np.isfinite(y).all():raise ValueError('Invalid training targets')
    return x,y


def fit(kind,data,ids,directory,experiment_id,rounds=96,max_chunks=None):
    if kind not in ('ridge','xgboost'):raise ValueError('Unknown baseline')
    if rounds<1 or rounds%4:raise ValueError('Boost rounds must be positive multiple of four')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    identity=dict(kind=kind,experiment_id=experiment_id,rounds=rounds,
        code_sha256=sha(Path(__file__)),data=getattr(data,'identities',['synthetic_test_fixture']),
        indices_sha256=hashlib.sha256(np.asarray(ids,dtype='int64').tobytes()).hexdigest())
    ip=directory/'baseline-identity.json'
    if ip.exists() and json.loads(ip.read_text())!=identity:raise ValueError('Baseline identity changed')
    if not ip.exists():atomic_json(ip,identity)
    completed=directory/'baseline-result.json'
    if completed.exists():
        result=json.loads(completed.read_text())
        for name,h in result['artifacts'].items():
            if sha(directory/name)!=h:raise ValueError('Baseline artifact changed')
        return load(kind,directory)
    x,y=training_rows(data,ids)
    if kind=='ridge':
        mean=x.mean(0,dtype='float64');std=np.maximum(x.std(0,dtype='float64'),1e-6)
        z=np.clip((x-mean)/std,-10,10);z=np.column_stack((np.ones(len(z)),z))
        penalty=np.eye(z.shape[1])*10.;penalty[0,0]=0
        weights=np.linalg.solve(z.T@z+penalty,z.T@y)
        with (directory/'ridge.part').open('wb') as f:
            np.savez(f,mean=mean,std=std,weights=weights);f.flush();os.fsync(f.fileno())
        os.replace(directory/'ridge.part',directory/'ridge.npz');artifacts=['ridge.npz']
    else:
        import xgboost as xgb
        params=dict(objective='reg:squarederror',tree_method='hist',device='cuda',
            max_depth=3,max_bin=64,eta=.04,reg_lambda=10.,min_child_weight=20,
            seed=7301,nthread=2,subsample=1.,colsample_bytree=1.,multi_strategy='one_output_per_tree')
        matrix=xgb.DMatrix(x,label=y*100,nthread=2);checkpoint=directory/'boost-progress.json'
        previous=None;start=0
        if checkpoint.exists():
            state=json.loads(checkpoint.read_text());previous=directory/state['file'];start=state['rounds']
            if sha(previous)!=state['sha256']:raise ValueError('Boost checkpoint changed')
        chunks=0
        for stop in range(start+4,rounds+1,4):
            thermal()
            model=xgb.train(params,matrix,num_boost_round=4,xgb_model=str(previous) if previous else None)
            if json.loads(model.save_config())['learner']['generic_param']['device']!='cuda:0':
                raise RuntimeError('XGBoost did not actually use CUDA')
            target=directory/f'boost-{stop}.ubj';part=directory/f'boost-{stop}.part.ubj'
            model.save_model(part)
            with part.open('rb') as f:os.fsync(f.fileno())
            os.replace(part,target)
            atomic_json(checkpoint,dict(rounds=stop,file=target.name,sha256=sha(target),ready=False))
            previous=target;chunks+=1
            if max_chunks is not None and chunks>=max_chunks and stop<rounds:return None
        if previous is None:raise ValueError('Missing boosted checkpoint')
        # The progress pointer is the authoritative completed tree artifact.
        artifacts=['boost-progress.json',previous.name]
    atomic_json(completed,dict(kind=kind,ready=False,training_rows=len(x),
        artifacts={name:sha(directory/name) for name in artifacts}))
    return load(kind,directory)


def load(kind,directory):
    directory=Path(directory)
    if kind=='ridge':
        with np.load(directory/'ridge.npz') as a:mean,std,weights=(a[k].copy() for k in ('mean','std','weights'))
        def predict(x):
            z=np.clip((features(x)-mean)/std,-10,10)
            return np.column_stack((np.ones(len(z)),z))@weights
    elif kind=='xgboost':
        import xgboost as xgb
        progress=json.loads((directory/'boost-progress.json').read_text());path=directory/progress['file']
        if sha(path)!=progress['sha256']:raise ValueError('Boost artifact changed')
        model=xgb.Booster();model.load_model(path);model.set_param({'device':'cpu','nthread':2})
        def predict(x):return model.predict(xgb.DMatrix(features(x),nthread=2))/100
    else:raise ValueError('Unknown baseline')
    return predict
