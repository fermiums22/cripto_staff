"""Training-only constant-feature contract for a future frozen PAPER adapter.

Never changes raw receipt times or execution freshness checks. Projection applies
ONLY to model input copies; real missing/extra channels remain in raw audit data.
Not wired into the active frozen historical competition or existing live controls.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
from brain_impulse_data import FEATURES,atomic_json
from brain_archive_stream import sha


def fit_contract(data,train_ids):
    ids=np.asarray(train_ids,dtype='int64')
    if not len(ids) or len(np.unique(ids))!=len(ids):raise ValueError('Empty or duplicate training indices')
    low=np.full(len(FEATURES),np.inf);high=np.full(len(FEATURES),-np.inf)
    for offset in range(0,len(ids),2048):
        x,_=data.batch(ids[offset:offset+2048]);x=np.asarray(x,dtype='float32')
        if x.ndim!=3 or x.shape[1:]!=(8,len(FEATURES)) or not np.isfinite(x).all():
            raise ValueError('Invalid training feature window')
        low=np.minimum(low,x.min((0,1)));high=np.maximum(high,x.max((0,1)))
    # Exact range, not the scaler's variance floor: low-variance signals survive.
    constant=np.flatnonzero(low==high)
    return dict(features=list(FEATURES),constant_indices=constant.tolist(),
        constant_values=low[constant].tolist(),constant_names=[FEATURES[i] for i in constant],
        train_indices_sha256=hashlib.sha256(ids.tobytes()).hexdigest(),
        data_identities=list(data.identities),source_sha256=sha(Path(__file__)),
        ready=False,scope='model_input_only',requires_validation_invariance=True)


def project(x,contract):
    if contract['features']!=list(FEATURES):raise ValueError('Feature order/schema mismatch')
    values=np.asarray(contract['constant_values'],dtype='float32')
    ids=np.asarray(contract['constant_indices'],dtype='int64')
    if len(ids)!=len(values) or len(np.unique(ids))!=len(ids) or np.any(ids<0) or np.any(ids>=len(FEATURES)):
        raise ValueError('Invalid feature contract indices')
    x=np.asarray(x,dtype='float32')
    if x.ndim!=3 or x.shape[1:]!=(8,len(FEATURES)) or not np.isfinite(x).all() or not np.isfinite(values).all():
        raise ValueError('Invalid live features or contract values')
    projected=x.copy();projected[:,:,ids]=values
    return projected


def verify_invariance(data,validation_ids,contract):
    """A new live contract must not silently change the validated model's inputs."""
    ids=np.asarray(validation_ids,dtype='int64')
    if not len(ids):raise ValueError('Empty validation')
    changed=0
    for offset in range(0,len(ids),2048):
        x,_=data.batch(ids[offset:offset+2048])
        changed+=int(np.count_nonzero(np.any(project(x,contract)!=x,axis=(1,2))))
    return dict(rows=len(ids),changed_windows=changed,input_invariant=changed==0,
        validation_indices_sha256=hashlib.sha256(ids.tobytes()).hexdigest(),ready=False)


def save_contract(path,contract,invariance):
    if not invariance['input_invariant'] or invariance['changed_windows']!=0:
        raise ValueError('Contract changes validation inputs; no silent prospective adaptation')
    value=dict(contract=contract,validation_invariance=invariance,ready=False)
    path=Path(path)
    if path.exists() and json.loads(path.read_text())!=value:raise ValueError('Frozen feature contract changed')
    if not path.exists():atomic_json(path,value)
    return sha(path)
