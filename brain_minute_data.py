"""Resumable public linear minute archive, strictly before reserved future trials."""
import argparse
import gzip
import json
import pathlib
import time
import urllib.parse
import urllib.request
import numpy as np
from brain_research import ROOT, STORE, SYMBOLS, digest, write


def collect(directory):
    directory.mkdir(parents=True,exist_ok=True)
    if (directory/'dataset.json').exists(): return
    plan=directory/'download-plan.json'
    if plan.exists():
        config=json.loads(plan.read_text())
    else:
        starts=[json.loads(p.read_text())['future_start_ms'] for p in STORE.glob('run-*/protocol.json')
                if 'future_start_ms' in json.loads(p.read_text())]
        if not starts: raise ValueError('No prospective reservation boundary found')
        end=(min(starts)//60000)*60000-60000
        config=dict(start_ms=end-30*86400000+60000,end_ms=end,symbols=SYMBOLS,
                    created_ms=int(time.time()*1000),endpoint='https://api.bybit.com/v5/market/kline',
                    category='linear',independent=False,excluded_future_start_ms=min(starts))
        write(plan,config)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    all_rows={};metadata={}
    for symbol in SYMBOLS:
        saved=directory/(symbol+'.json')
        rows=json.loads(saved.read_text()) if saved.exists() else []
        seen={int(r[0]):r for r in rows}
        end=min(seen)-60000 if seen else config['end_ms']
        while end>=config['start_ms']:
            query=urllib.parse.urlencode(dict(category='linear',symbol=symbol,interval='1',
                                             limit=1000,start=config['start_ms'],end=end))
            with opener.open(config['endpoint']+'?'+query,timeout=20) as response:
                result=json.load(response)
            if result.get('retCode')!=0: raise RuntimeError('public kline request rejected')
            batch=result['result']['list']
            if not batch: raise ValueError('Missing minute history')
            parsed=[[float(v) for v in row[:6]] for row in batch]
            if min(r[0] for r in parsed)>end: raise ValueError('Pagination did not advance')
            for row in parsed:
                if config['start_ms']<=row[0]<=config['end_ms']:seen[int(row[0])]=row
            write(saved,[seen[k] for k in sorted(seen)])
            end=int(min(r[0] for r in parsed))-60000
            print(json.dumps(dict(symbol=symbol,rows=len(seen),remaining_minutes=max(0,(end-config['start_ms'])//60000))),flush=True)
            time.sleep(.15)
        all_rows[symbol]=seen
        with gzip.open(ROOT/'data/portfolio'/(symbol+'.json.gz'),'rt') as f:old=json.load(f)
        metadata[symbol]=dict(instrument=old['instrument'],funding=old['funding'])
        # Retrieve funding covering the exact development interval, using public GET.
        query=urllib.parse.urlencode(dict(category='linear',symbol=symbol,
            startTime=config['start_ms'],endTime=config['end_ms']+60000,limit=200))
        with opener.open('https://api.bybit.com/v5/market/funding/history?'+query,timeout=20) as response:
            funding=json.load(response)
        if funding.get('retCode')!=0 or len(funding['result']['list'])>=200:
            raise ValueError('Funding missing or requires pagination')
        metadata[symbol]['funding']=funding['result']['list']
    ts=np.arange(config['start_ms'],config['end_ms']+1,60000,dtype='int64')
    if any(any(int(t) not in all_rows[s] for t in ts) for s in SYMBOLS):
        raise ValueError('Minute archive has gaps; no interpolation allowed')
    bars=np.array([[all_rows[s][int(t)] for s in SYMBOLS] for t in ts])
    if not np.isfinite(bars).all():raise ValueError('Nonfinite market data')
    np.savez_compressed(directory/'bars.npz',ts=ts,bars=bars)
    write(directory/'metadata.json',metadata)
    write(directory/'dataset.json',dict(**config,rows=len(ts),
        bars_sha256=digest(directory/'bars.npz'),metadata_sha256=digest(directory/'metadata.json'),
        limitation='Historical minute OHLC proxy; instrument rules are current snapshots'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=pathlib.Path,required=True)
    collect(parser.parse_args().directory)
