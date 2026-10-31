"""Bounded one-second depth tape for EXPLORATION; never final execution evidence."""
import json
import os
from pathlib import Path
import numpy as np
from brain_archive_stream import sha
from brain_impulse_data import atomic_json
from brain_impulse_dataset import ASSETS
from brain_impulse_replay import archive_events


def prepare(plan,output):
    plan=Path(plan);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    identity=dict(plan_sha256=sha(plan),source_sha256=sha(Path(__file__)),
        dependencies={n:sha(Path(__file__).parent/n) for n in ('brain_impulse_replay.py','brain_archive_stream.py','brain_impulse_data.py')},
        book_interval_ms=1000,levels=10,mode='EXPLORATION',ready=False)
    manifest=output/'manifest.json';target=output/'tape.npz'
    if manifest.exists():
        saved=json.loads(manifest.read_text())
        if saved['identity']!=identity or sha(target)!=saved['sha256']:raise ValueError('Tape identity changed')
        return target
    times=[];symbols=[];depth=[];ft=[];fs=[];fx=[];last={}
    for event in archive_events(plan):
        book=event['book'];sample=event['sample']
        if book and book['symbol'] in ASSETS and book['ts']-last.get(book['symbol'],0)>=1000:
            symbol=book['symbol'];last[symbol]=book['ts'];levels=np.zeros((2,10,2),dtype='float64')
            for side,key in enumerate(('bids','asks')):
                values=book[key][:10];levels[side,:len(values)]=values
            times.append(book['ts']);symbols.append(ASSETS.index(symbol));depth.append(levels)
        if sample and sample['symbol'] in ASSETS:
            ft.append(sample['ts']);fs.append(ASSETS.index(sample['symbol']));fx.append(sample['x'])
    with (output/'tape.part').open('wb') as f:
        np.savez(f,bt=np.asarray(times,dtype='int64'),bs=np.asarray(symbols,dtype='int8'),
            depth=np.asarray(depth),ft=np.asarray(ft,dtype='int64'),fs=np.asarray(fs,dtype='int8'),fx=np.asarray(fx,dtype='float32'))
        f.flush();os.fsync(f.fileno())
    os.replace(output/'tape.part',target)
    atomic_json(manifest,dict(identity=identity,sha256=sha(target),books=len(times),samples=len(ft),ready=False))
    return target


def load(path):
    with np.load(path) as a:return {k:a[k] for k in a.files}
