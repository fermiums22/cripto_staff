"""Cluster-aware descriptive summary. Outcomes of one impulse are not new events."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import numpy as np
from brain_archive_stream import sha
from brain_impulse_data import atomic_json


def summarize(directory,output):
    groups=defaultdict(list);inputs={};events=defaultdict(set);audits={}
    for p in sorted(directory.glob('2026-*.json')):
        digest=p.with_suffix('.sha256')
        if not digest.exists():continue
        h=sha(p)
        if h!=digest.read_text().strip():raise ValueError('Event day checksum changed')
        inputs[p.name]=h;r=json.loads(p.read_text());audits[p.stem]=r['audit']
        for s in r['signals']:events[s['leader']].add((p.stem,s['signal_ms']))
        for x in r['outcomes']:
            key=tuple(x[k] for k in ('leader','delay_ms','horizon_ms','alignment','stratum'))
            groups[key].append(dict(x,day=p.stem))
    result=[]
    for key,rows in groups.items():
        clusters=defaultdict(list);days=defaultdict(list);coins=defaultdict(list)
        for r in rows:
            clusters[(r['day'],r['signal_ms'])].append(r['net_return']);coins[r['symbol']].append(r['net_return'])
        for (day,_),values in clusters.items():days[day].append(float(np.mean(values)))
        result.append(dict(zip(('leader','delay_ms','horizon_ms','alignment','stratum'),key),
            outcomes=len(rows),event_clusters=len(clusters),mean_event_net=float(np.mean([np.mean(v) for v in clusters.values()])),
            by_day={k:dict(events=len(v),mean_net=float(np.mean(v))) for k,v in days.items()},
            by_coin={k:dict(outcomes=len(v),mean_net=float(np.mean(v))) for k,v in coins.items()},
            ready=False))
    atomic_json(output,dict(inputs=inputs,signals={k:len(v) for k,v in events.items()},groups=result,audits=audits,
        independent_evidence=False,ready=False,
        caution='Descriptive historical clusters; small day count, multiple fixed comparisons, no promotion'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();summarize(a.directory,a.output)
