"""Bounded official Bybit archive probe; development data, not live receipt evidence."""
import argparse
from datetime import date,datetime,timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import urllib.request
import zipfile
from brain_impulse_data import atomic_json


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while block:=f.read(1024*1024):h.update(block)
    return h.hexdigest()


def probe(directory,day,symbol='SOLUSDT',max_file_bytes=256*1024**2):
    if symbol not in ('BTCUSDT','ETHUSDT','SOLUSDT','DOGEUSDT','XRPUSDT','BNBUSDT'):
        raise ValueError('Symbol outside the fixed research universe')
    parsed=date.fromisoformat(day)
    if parsed>=datetime.now(timezone.utc).date():raise ValueError('Closed historical day required')
    directory.mkdir(parents=True,exist_ok=True)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    sources={f'{symbol}{day}.csv.gz':f'https://public.bybit.com/trading/{symbol}/{symbol}{day}.csv.gz',
        f'{day}_{symbol}_ob200.data.zip':f'https://quote-saver.bycsi.com/orderbook/linear/{symbol}/{day}_{symbol}_ob200.data.zip'}
    reports=[]
    for name,url in sources.items():
        target=directory/name;manifest=directory/(name+'.json')
        if target.exists():
            previous=json.loads(manifest.read_text())
            if sha(target)!=previous['sha256']:raise ValueError('Downloaded archive changed')
            reports.append(previous);continue
        with opener.open(urllib.request.Request(url,method='HEAD'),timeout=20) as response:
            size=int(response.headers['Content-Length']);etag=response.headers.get('ETag')
        if not 0<size<max_file_bytes or shutil.disk_usage(directory).free-size<10*1024**3:
            raise ValueError('Archive probe storage budget')
        part=directory/(name+'.part');partmeta=directory/(name+'.part.json')
        metadata=dict(url=url,size=size,etag=etag)
        if partmeta.exists() and json.loads(partmeta.read_text())!=metadata:
            raise ValueError('Partial download source changed; preserve for inspection')
        atomic_json(partmeta,metadata)
        offset=part.stat().st_size if part.exists() else 0
        if offset>size:raise ValueError('Partial exceeds expected length')
        if offset<size:
            headers={'Range':f'bytes={offset}-'} if offset else {}
            with opener.open(urllib.request.Request(url,headers=headers),timeout=30) as response:
                if offset and (response.status!=206 or not response.headers.get('Content-Range','').startswith(f'bytes {offset}-')):
                    raise ValueError('Unsafe partial response; archive not overwritten')
                with part.open('ab') as output:
                    total=offset
                    while block:=response.read(1024*1024):
                        total+=len(block)
                        if total>size:raise ValueError('Unexpected oversized response')
                        output.write(block)
                    output.flush();os.fsync(output.fileno())
            if total!=size:raise ValueError('Incomplete archive, retry resumes the partial')
        if name.endswith('.zip'):
            with zipfile.ZipFile(part) as archive:
                members=archive.namelist()
                if len(members)!=1:raise ValueError('Unexpected archive layout')
                with archive.open(members[0]) as f:
                    first=f.readline(1024*1024)
                message=json.loads(first)
                stamp=int(message['ts'])
                if datetime.fromtimestamp(stamp/1000,timezone.utc).date()!=parsed:
                    raise ValueError('Archive timestamp outside requested date')
                schema=dict(member=members[0],keys=list(message),topic=message.get('topic'),
                    first_event_ms=stamp,type=message.get('type'),data_keys=list(message.get('data',{})))
        else:
            with gzip.open(part,'rt') as f:
                schema=dict(header=f.readline().strip().split(','),first_row=f.readline().strip().split(','))
        report=dict(url=url,bytes=size,etag=etag,sha256=sha(part),schema=schema,
            independent_paper_evidence=False,local_receipt_timestamps_available=False,
            limitation='Exchange archive only: delay scenarios and future live PAPER are required')
        # Manifest precedes publication: a crash after rename can always verify it.
        atomic_json(manifest,report);os.replace(part,target);reports.append(report)
        print(json.dumps(dict(file=name,bytes=size,schema=schema)),flush=True)
    atomic_json(directory/'probe.json',dict(reports=reports,ready=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--date',required=True);p.add_argument('--symbol',default='SOLUSDT')
    a=p.parse_args();probe(a.directory,a.date,a.symbol)
