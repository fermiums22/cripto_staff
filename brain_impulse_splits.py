"""Calendar-covered, purged development folds. Final seven days stay unopened.

Only manifest hashes/coverage are inspected on the diagnostic block. Historical
data remain development evidence; success still requires a new independent trial.
"""
import datetime as dt
import json
from pathlib import Path
import numpy as np
from brain_archive_stream import sha
from brain_impulse_data import atomic_json
from brain_impulse_dataset import ASSETS
from brain_impulse_protocol import DAY

PURGE=180000
# (train end, early-stop end, validation replay end), offsets in calendar days.
FOLDS=((7,9,11),(9,11,14))


def indices(data,start_ms,train_end,early_end,score_end):
    times=np.asarray(data.times);ends=np.asarray(data.ends);starts=np.asarray(data.input_start_ms)
    if not (times.shape==ends.shape==starts.shape) or not len(times):raise ValueError('Invalid sample intervals')
    if np.any(starts>times) or np.any(ends<times):raise ValueError('Noncausal sample interval')
    if not start_ms<train_end<early_end<score_end:raise ValueError('Invalid fold boundaries')
    result=[]
    for left,right in ((start_ms,train_end),(train_end,early_end),(early_end,score_end)):
        ids=np.flatnonzero((starts>=left+PURGE)&(ends<right-PURGE))
        if not len(ids):raise ValueError('Empty purged fold')
        result.append(ids[np.argsort(times[ids],kind='stable')])
    for left,right in zip(result,result[1:]):
        if ends[left].max()>=starts[right].min():raise ValueError('Temporal leakage')
    return tuple(result)


def campaign_manifest(directory):
    directory=Path(directory);summary=json.loads((directory/'summary.json').read_text())
    plan=directory/'campaign-plan.json';days=summary['days']
    if summary.get('coverage_admitted') is not True or len(days)!=21:
        raise ValueError('Require all 21 covered development days')
    stamps=[];records=[]
    for report in days:
        day=dt.datetime.strptime(report['day'],'%Y-%m-%d').replace(tzinfo=dt.timezone.utc)
        stamp=int(day.timestamp()*1000);stamps.append(stamp)
        if report['campaign_sha256']!=sha(plan):raise ValueError('Mixed campaign identity')
        if set(report['qualified_hours'])!=set(ASSETS) or any(v<20 for v in report['qualified_hours'].values()):
            raise ValueError('Incomplete market-day coverage')
        dataset=Path(report['dataset'])
        if sha(dataset/'dataset.json')!=report['dataset_manifest_sha256']:raise ValueError('Dataset manifest changed')
        records.append(dict(day=report['day'],dataset=str(dataset),sha256=report['dataset_manifest_sha256']))
    if any(b-a!=DAY for a,b in zip(stamps,stamps[1:])):raise ValueError('Noncontiguous or unordered days')
    start=stamps[0]
    return dict(campaign_sha256=sha(plan),summary_sha256=sha(directory/'summary.json'),
        start_ms=start,end_ms=start+21*DAY,development=records[:14],diagnostic=records[14:],
        folds=[dict(train_end_ms=start+a*DAY,early_end_ms=start+b*DAY,score_end_ms=start+c*DAY)
               for a,b,c in FOLDS],purge_ms=PURGE,ready=False,
        diagnostic_rule='Do not load diagnostic arrays until validation selection is frozen',
        independent_paper_evidence=False)


def freeze(directory,output):
    manifest=campaign_manifest(directory)
    manifest['split_code_sha256']=sha(Path(__file__))
    output=Path(output);output.mkdir(parents=True,exist_ok=True);target=output/'split-plan.json'
    if target.exists() and json.loads(target.read_text())!=manifest:
        raise ValueError('Frozen split plan changed; preserve prior experiment')
    if not target.exists():atomic_json(target,manifest)
    return manifest
