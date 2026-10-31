"""Causal streaming merge of Bybit trade CSV and L2 JSONL archives.

Exchange archives do not contain historical client receipt timestamps. Every
derived receipt time below is explicitly a latency scenario, never a measurement.
The complete compressed streams are read to EOF so gzip/ZIP CRCs are checked.
"""
import argparse
from collections import Counter
import csv
from datetime import date,datetime,timezone
from decimal import Decimal
import gzip
import hashlib
import heapq
import io
import json
import math
import os
from pathlib import Path
import time
import zipfile

from brain_impulse_data import ImpulseSampler,FEATURES,atomic_json


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while block:=f.read(1024*1024):h.update(block)
    return h.hexdigest()


class ArchiveSource:
    def __init__(self,path,symbol,day,kind,delay_ms):
        if kind not in ('book','trades') or not 0<=delay_ms<=1500:
            raise ValueError('Unsupported source or latency scenario')
        self.path=Path(path);self.symbol=symbol;self.day=day;self.kind=kind;self.delay_ms=delay_ms
        self.start=int(datetime.combine(date.fromisoformat(day),datetime.min.time(),timezone.utc).timestamp()*1000)
        self.stats=dict(records=0,emitted=0,rpi_filtered=0,time_regressions=0,boundary_records_excluded=0,
                        first_event_ms=None,last_event_ms=None,max_event_gap_ms=0,crc_complete=False)
        self.minutes=set();self.previous_event=None;self.previous_received=-1

    def row(self,message,event_ms):
        if not self.start<=event_ms<self.start+86400000:
            # Official daily files include a short overlap beyond midnight. Clip
            # to the predeclared UTC interval; still consume EOF for CRC checking.
            if self.start-60000<=event_ms<=self.start+86400000+60000:
                self.stats['boundary_records_excluded']+=1
                return None
            raise ValueError('Record timestamp far outside named UTC day: '+str(self.path))
        if self.previous_event is not None:
            gap=event_ms-self.previous_event
            self.stats['time_regressions']+=int(gap<0)
            self.stats['max_event_gap_ms']=max(self.stats['max_event_gap_ms'],gap)
        self.previous_event=event_ms
        if self.stats['first_event_ms'] is None:self.stats['first_event_ms']=event_ms
        self.stats['last_event_ms']=event_ms;self.minutes.add(event_ms//60000)
        # Preserve within-file arrival order. An older event is not moved backwards
        # to let a simulated trader learn it before the preceding record arrived.
        received=max(event_ms+self.delay_ms,self.previous_received)
        self.previous_received=received;self.stats['emitted']+=1
        return dict(session='archive:'+self.day,received_ms=received,message=message,
                    receipt_source='simulated_exchange_time_plus_delay',source_kind=self.kind)

    def __iter__(self):
        if self.stats['records']:raise ValueError('ArchiveSource is single-pass')
        if self.kind=='book':
            with zipfile.ZipFile(self.path) as archive:
                members=archive.namelist()
                if len(members)!=1 or not members[0].endswith('.data'):
                    raise ValueError('Unexpected orderbook archive layout')
                with archive.open(members[0]) as raw:
                    for line in raw:
                        if len(line)>4*1024**2:raise ValueError('Oversized orderbook record')
                        self.stats['records']+=1;m=json.loads(line)
                        if m.get('topic')!='orderbook.200.'+self.symbol or m['data'].get('s')!=self.symbol:
                            raise ValueError('Orderbook symbol mismatch')
                        if m.get('type') not in ('snapshot','delta'):raise ValueError('Unknown book message type')
                        row=self.row(m,int(m['ts']))
                        if row is not None:yield row
        else:
            with gzip.open(self.path,'rt',newline='') as f:
                reader=csv.DictReader(f)
                required={'timestamp','symbol','side','size','price','RPI'}
                if not required.issubset(reader.fieldnames or []):raise ValueError('Trade archive schema missing fields')
                for t in reader:
                    self.stats['records']+=1
                    if t['symbol']!=self.symbol or t['side'] not in ('Buy','Sell'):
                        raise ValueError('Invalid trade symbol or side')
                    if t['RPI'] not in ('0','1'):raise ValueError('Unknown RPI indicator')
                    if t['RPI']=='1':self.stats['rpi_filtered']+=1;continue
                    p,v=float(t['price']),float(t['size'])
                    if not math.isfinite(p*v) or min(p,v)<=0:raise ValueError('Invalid trade value')
                    stamp=int(Decimal(t['timestamp'])*1000)
                    m=dict(topic='publicTrade.'+self.symbol,ts=stamp,data=[dict(
                        T=stamp,s=self.symbol,S=t['side'],v=t['size'],p=t['price'])])
                    row=self.row(m,stamp)
                    if row is not None:yield row
        self.stats['crc_complete']=True
        self.stats['covered_minutes']=len(self.minutes)


def merged(sources):
    """Bounded memory: one head record per source, original order retained on ties."""
    return heapq.merge(*(iter(source) for source in sources),key=lambda row:row['received_ms'])


def extract(plan_path,output):
    plan=json.loads(plan_path.read_text())
    if plan['mode']!='historical_development_only':raise ValueError('Archive cannot become live PAPER evidence')
    output.mkdir(parents=True,exist_ok=True)
    manifest=output/'manifest.json'
    code={name:sha(Path(__file__).parent/name) for name in ('brain_archive_stream.py','brain_impulse_data.py')}
    identity=dict(plan_sha256=sha(plan_path),code_sha256=code)
    if manifest.exists():
        report=json.loads(manifest.read_text())
        if report['identity']!=identity:raise ValueError('Completed extraction identity changed')
        if sha(output/'samples.jsonl.gz')!=report['samples_sha256']:raise ValueError('Derived samples changed')
        return report
    frozen=output/'identity.json'
    if frozen.exists() and json.loads(frozen.read_text())!=identity:
        raise ValueError('Interrupted extraction identity changed; preserve old attempt')
    atomic_json(frozen,identity)
    sources=[]
    for spec in plan['sources']:
        path=Path(spec['path'])
        if sha(path)!=spec['sha256']:raise ValueError('Raw archive changed: '+path.name)
        sources.append(ArchiveSource(path,spec['symbol'],spec['day'],spec['kind'],spec['delay_ms']))
    sampler=ImpulseSampler();count=0;samples=0;first=None;last=None;by_symbol=Counter();minute_bins=set()
    tmp=output/'samples.jsonl.gz.part';last_report=time.monotonic()
    with gzip.open(tmp,'wt',compresslevel=3) as f:
        for row in merged(sources):
            sample=sampler.ingest(row);count+=1
            if sample:
                sample['receipt_source']='simulated_exchange_time_plus_delay'
                sample['unavailable_channels']=['open_interest','funding','liquidations','news']
                f.write(json.dumps(sample,separators=(',',':'),allow_nan=False)+'\n')
                samples+=1;by_symbol[sample['symbol']]+=1
                minute_bins.add((sample['symbol'],sample['ts']//60000))
                first=sample['ts'] if first is None else first;last=sample['ts']
            if time.monotonic()-last_report>=10:
                f.flush()
                atomic_json(output/'progress.json',dict(stage='extracting',messages=count,samples=samples,
                    last_received_ms=row['received_ms'],updated_ms=time.time_ns()//1000000,ready=False))
                last_report=time.monotonic()
    if not all(s.stats['crc_complete'] for s in sources):raise ValueError('Incomplete archive consumption')
    with tmp.open('rb') as f:os.fsync(f.fileno())
    target=output/'samples.jsonl.gz';os.replace(tmp,target)
    report=dict(identity=identity,samples_sha256=sha(target),messages=count,samples=samples,
        features=FEATURES,first_received_ms=first,last_received_ms=last,by_symbol=dict(by_symbol),
        covered_minutes={s:sum(symbol==s for symbol,_ in minute_bins) for s in by_symbol},
        sources=[dict(path=str(s.path),symbol=s.symbol,kind=s.kind,delay_ms=s.delay_ms,**s.stats) for s in sources],
        sampler_audit=dict(sampler.audit),ready=False,independent_paper_evidence=False,
        limitations=['Receipt times are explicit simulations, not historical client measurements',
            'No OI/funding/liquidation/news observations are invented',
            'Public depth excludes hidden/RPI liquidity','Instrument rules need point-in-time audit'])
    atomic_json(manifest,report);atomic_json(output/'progress.json',dict(stage='complete',samples=samples,ready=False))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=extract(a.plan,a.output)
    print(json.dumps({k:v for k,v in result.items() if k not in ('sources','features')}),flush=True)
