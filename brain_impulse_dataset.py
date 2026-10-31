"""Memory-bounded sequence/target preparation, with immutable reservation exclusion.

Targets are fixed-horizon, unstopped, sampled-depth net-return proxies. They are
supervision for a model, not a claim of portfolio execution performance. Portfolio
risk/stops and independent live execution must be assessed separately.
"""
import argparse
from collections import defaultdict,deque
import gzip
import json
import os
from pathlib import Path
import time
import numpy as np
from brain_archive_stream import sha
from brain_impulse_data import FEATURES,atomic_json,execution_label

HORIZONS=(10000,30000,60000,120000)
LENGTH=8
ASSETS=('SOLUSDT','DOGEUSDT','XRPUSDT','BNBUSDT')
FILES={'features':('float32',len(FEATURES)),'feature_ms':('int64',1),
       'windows':('int64',LENGTH),'targets':('float32',8),
       'signal_ms':('int64',1),'exit_ms':('int64',1),'symbols':('int8',1)}


def intersects(start,end,reservations):
    return any(end>=a and start<b for a,b in reservations)


def prepare(samples,instruments,output,reservations=()):
    output.mkdir(parents=True,exist_ok=True)
    metadata=json.loads(instruments.read_text())
    inst=metadata.get('instruments',metadata)
    identity=dict(samples_sha256=sha(samples),instruments_sha256=sha(instruments),
        reservations=[list(r) for r in reservations],code_sha256={name:sha(Path(__file__).parent/name)
            for name in ('brain_impulse_dataset.py','brain_impulse_data.py')})
    manifest=output/'dataset.json'
    if manifest.exists():
        result=json.loads(manifest.read_text())
        if result['identity']!=identity:raise ValueError('Completed dataset identity changed')
        for name,h in result['artifact_hashes'].items():
            if sha(output/name)!=h:raise ValueError('Dataset artifact modified')
        return result
    frozen=output/'identity.json'
    if frozen.exists() and json.loads(frozen.read_text())!=identity:
        raise ValueError('Interrupted dataset identity changed')
    atomic_json(frozen,identity)
    writers={name:(output/(name+'.bin.part')).open('wb') for name in FILES}
    history=defaultdict(lambda:deque(maxlen=LENGTH));pending=defaultdict(list)
    last={};feature_count=0;target_count=0;excluded=0;gaps=0;quantity_rejections=0
    previous=-1;minute_bins=set();receipts=set()
    def write(name,values):
        writers[name].write(np.asarray(values,dtype=FILES[name][0]).tobytes())
    try:
        with gzip.open(samples,'rt') as f:
            for line in f:
                row=json.loads(line);symbol=row['symbol'];now=int(row['ts'])
                if now<previous:raise ValueError('Samples must be chronologically merged')
                previous=now
                if symbol not in ASSETS:continue
                receipts.add(row.get('receipt_source','unspecified'))
                if receipts!={'simulated_exchange_time_plus_delay'}:
                    raise ValueError('Do not mix archive latency scenarios with live receipt data')
                # Purge feature lookback and maximum label tail BEFORE making targets.
                if intersects(now-60000,now+180000,reservations):
                    excluded+=1;pending[symbol].clear();history[symbol].clear();last.pop(symbol,None);continue
                if symbol in last and (row['session']!=last[symbol][1] or now-last[symbol][0]>7000):
                    gaps+=1;pending[symbol].clear();history[symbol].clear()
                last[symbol]=(now,row['session']);minute_bins.add((symbol,now//60000))
                remaining=[]
                for item in pending[symbol]:
                    if item['ts']//3600000!=now//3600000:continue
                    if item['entry'] is None:
                        if now-item['ts']<1000:remaining.append(item);continue
                        item['entry']=row
                    entry=item['entry']
                    invalid=False
                    for h,horizon in enumerate(HORIZONS):
                        if item['targets'][2*h] is not None:continue
                        if item['due'][h] is None and now>=entry['ts']+horizon:
                            item['due'][h]=now+1000
                        if item['due'][h] is not None and now>=item['due'][h]:
                            for j,side in enumerate((1,-1)):
                                result=execution_label(entry,row,inst[symbol]['lotSizeFilter'],side)
                                if result is None:invalid=True;quantity_rejections+=1;break
                                item['targets'][2*h+j]=result['net_return']
                            item['exit_ms']=now
                    if invalid:continue
                    if all(y is not None for y in item['targets']):
                        write('windows',item['window']);write('targets',item['targets'])
                        write('signal_ms',[item['ts']]);write('exit_ms',[item['exit_ms']])
                        write('symbols',[ASSETS.index(symbol)]);target_count+=1
                    else:remaining.append(item)
                pending[symbol]=remaining
                x=np.asarray(row['x'],dtype='float32')
                if x.shape!=(len(FEATURES),) or not np.isfinite(x).all():raise ValueError('Invalid feature vector')
                write('features',x);write('feature_ms',[now])
                history[symbol].append(feature_count);feature_count+=1
                if len(history[symbol])==LENGTH:
                    pending[symbol].append(dict(ts=now,entry=None,window=list(history[symbol]),
                        targets=[None]*8,due=[None]*4,exit_ms=None))
        for f in writers.values():f.flush();os.fsync(f.fileno());f.close()
        for name in FILES:os.replace(output/(name+'.bin.part'),output/(name+'.bin'))
        report=dict(identity=identity,features=FEATURES,assets=ASSETS,length=LENGTH,
            outputs=[dict(horizon_ms=h,side=side) for h in HORIZONS for side in (1,-1)],
            feature_rows=feature_count,target_rows=target_count,excluded_reserved=excluded,
            gap_resets=gaps,quantity_rejections=quantity_rejections,
            covered_minutes={s:sum(symbol==s for symbol,_ in minute_bins) for s in ASSETS},
            qualified_hours={s:sum(sum(symbol==s and minute//60==hour for symbol,minute in minute_bins)>=45
                for hour in {minute//60 for symbol,minute in minute_bins if symbol==s}) for s in ASSETS},
            format=FILES,artifact_hashes={name+'.bin':sha(output/(name+'.bin')) for name in FILES},
            ready=False,target_protocol='sampled_depth_fixed_horizon_unstopped_net_return',
            target_order='completion_time; sort signal_ms before chronological splits',
            limitations=['Historical instrument rules unavailable: supplied snapshot is a scenario',
                'Archive receipt and execution delays are simulated',
                'Risk-stopped portfolio replay and independent live PAPER still required'])
        report=json.loads(json.dumps(report))
        atomic_json(manifest,report);return report
    finally:
        for f in writers.values():f.close()


def load(directory):
    meta=json.loads((directory/'dataset.json').read_text());arrays={}
    for name,(dtype,width) in FILES.items():
        count=meta['feature_rows'] if name in ('features','feature_ms') else meta['target_rows']
        shape=(count,width) if width>1 else (count,)
        path=directory/(name+'.bin')
        if path.stat().st_size!=np.dtype(dtype).itemsize*count*width:raise ValueError('Truncated dataset')
        arrays[name]=np.memmap(path,dtype=dtype,mode='r',shape=shape) if count else np.empty(shape,dtype=dtype)
    return meta,arrays


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--samples',type=Path,required=True)
    p.add_argument('--instruments',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--reservations',type=Path,required=True);a=p.parse_args()
    reservations=[]
    for path in a.reservations.glob('run-*/protocol.json'):
        item=json.loads(path.read_text())
        if 'future_start_ms' in item:reservations.append((item['future_start_ms'],item['future_end_ms']))
    result=prepare(a.samples,a.instruments,a.output,reservations)
    print(json.dumps({k:result[k] for k in ('feature_rows','target_rows','excluded_reserved','gap_resets','ready')}))
