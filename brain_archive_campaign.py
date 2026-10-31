"""Fixed 21-day development archive campaign, finite and resumable per day.

This collects causal feature/target data only. It cannot qualify or deploy a model.
No observations from reserved future trials are admitted; no calendar-day search.
"""
import argparse
import fcntl
import json
from pathlib import Path
import shutil
import time
from brain_archive_probe import probe
from brain_archive_stream import extract,sha
from brain_impulse_dataset import prepare
from brain_impulse_data import atomic_json

ROOT=Path(__file__).resolve().parent
CODE=('brain_archive_campaign.py','brain_archive_probe.py','brain_archive_stream.py',
      'brain_impulse_dataset.py','brain_impulse_data.py')


def run(directory):
    lock=(directory/'campaign.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    path=directory/'campaign-plan.json';preflight=json.loads((directory/'preflight.json').read_text())
    hashes={name:sha(ROOT/name) for name in CODE}
    if not path.exists():
        if preflight['errors'] or preflight['total_bytes']>32*1024**3 or preflight['max_file_bytes']>=512*1024**2:
            raise ValueError('Campaign preflight exceeds fixed budget or has missing sources')
        if shutil.disk_usage(directory).free-preflight['total_bytes']<10*1024**3:
            raise ValueError('Insufficient storage reserve')
        reservations=[];reserved_files={}
        for p in (directory.parent/'evidence-v1').glob('run-*/protocol.json'):
            d=json.loads(p.read_text());reserved_files[str(p)]=sha(p)
            if 'future_start_ms' in d:reservations.append([d['future_start_ms'],d['future_end_ms']])
        plan=dict(preflight_sha256=sha(directory/'preflight.json'),sources=preflight['sources'],
            code_sha256=hashes,created_ms=time.time_ns()//1000000,reservations=reservations,
            instrument_sha256=sha(directory.parent/'archive-pilot-v1/instrument-scenario.json'),
            reservation_files=reserved_files,raw_budget_bytes=32*1024**3,
            mode='historical_development_only',book_delay_ms=250,trade_delay_ms=350,
            ready=False,independent_paper_evidence=False)
        atomic_json(path,plan)
    plan=json.loads(path.read_text())
    if hashes!=plan['code_sha256'] or sha(directory/'preflight.json')!=plan['preflight_sha256']:
        raise ValueError('Frozen campaign code/preflight changed')
    for name,h in plan['reservation_files'].items():
        if sha(Path(name))!=h:raise ValueError('Frozen reservation changed')
    if (directory/'summary.json').exists():return
    reports=[];pilot=directory.parent/'archive-pilot-v1'
    metadata=directory/'instrument-scenario.json'
    if not metadata.exists():metadata.write_bytes((pilot/'instrument-scenario.json').read_bytes())
    if sha(metadata)!=plan['instrument_sha256']:raise ValueError('Frozen instrument scenario changed')
    for day in sorted({s['day'] for s in plan['sources']}):
        if {name:sha(ROOT/name) for name in CODE}!=hashes:raise ValueError('Campaign source changed while running')
        if sha(metadata)!=plan['instrument_sha256']:raise ValueError('Instrument scenario changed while running')
        folder=directory/day;folder.mkdir(exist_ok=True)
        saved=folder/'result.json'
        if saved.exists():
            report=json.loads(saved.read_text())
            if report['campaign_sha256']!=sha(path):raise ValueError('Day belongs to another campaign')
            if sha(Path(report['dataset'])/'dataset.json')!=report['dataset_manifest_sha256']:
                raise ValueError('Prepared dataset manifest changed')
            reports.append(report);continue
        atomic_json(directory/'status.json',dict(stage='downloading',day=day,completed_days=len(reports),ready=False))
        specs=[s for s in plan['sources'] if s['day']==day];sources=[]
        for symbol in sorted({s['symbol'] for s in specs}):
            if day=='2026-10-01':
                raw=directory.parent/'archive-probe-20261001' if symbol=='SOLUSDT' else pilot/'raw'/symbol
            else:raw=folder/'raw'/symbol
            probe(raw,day,symbol,max_file_bytes=512*1024**2)
            for report in json.loads((raw/'probe.json').read_text())['reports']:
                spec=next(s for s in specs if s['url']==report['url'])
                if spec['bytes']!=report['bytes'] or spec['etag']!=report['etag']:
                    raise ValueError('Archive changed after preflight')
                sources.append(dict(path=str(raw/report['url'].split('/')[-1]),symbol=symbol,day=day,
                    kind=spec['kind'],sha256=report['sha256'],delay_ms=plan['book_delay_ms'] if spec['kind']=='book' else plan['trade_delay_ms']))
        atomic_json(directory/'status.json',dict(stage='extracting',day=day,completed_days=len(reports),ready=False))
        if day=='2026-10-01':
            derived=Path(json.loads((pilot/'status.json').read_text())['derived'])
            existing=json.loads((derived/'manifest.json').read_text())
            if existing['identity']['code_sha256']['brain_archive_stream.py']!=sha(ROOT/'brain_archive_stream.py'):
                raise ValueError('Pilot extractor differs from campaign')
            if sha(derived/'samples.jsonl.gz')!=existing['samples_sha256']:raise ValueError('Pilot data changed')
        else:
            ep=folder/'extraction-plan.json'
            value=dict(mode='historical_development_only',sources=sources,campaign_sha256=sha(path),ready=False)
            if ep.exists() and json.loads(ep.read_text())!=value:raise ValueError('Day extraction plan changed')
            atomic_json(ep,value);derived=folder/'derived';extract(ep,derived)
        atomic_json(directory/'status.json',dict(stage='targets',day=day,completed_days=len(reports),ready=False))
        data=prepare(derived/'samples.jsonl.gz',metadata,folder/'dataset',plan['reservations'])
        if {name:sha(ROOT/name) for name in CODE}!=hashes:raise ValueError('Source mutation during day preparation')
        report=dict(day=day,dataset=str(folder/'dataset'),dataset_manifest_sha256=sha(folder/'dataset/dataset.json'),
            campaign_sha256=sha(path),feature_rows=data['feature_rows'],target_rows=data['target_rows'],
            qualified_hours=data['qualified_hours'],coverage_pass=all(v>=20 for v in data['qualified_hours'].values()),
            ready=False)
        atomic_json(saved,report);reports.append(report)
        print(json.dumps(dict(day=day,targets=data['target_rows'],completed_days=len(reports),coverage_pass=report['coverage_pass'])),flush=True)
    summary=dict(days=reports,total_targets=sum(r['target_rows'] for r in reports),
        coverage_admitted=len(reports)==21 and all(r['coverage_pass'] for r in reports),
        ready=False,reason='Development data only; frozen GPU competition and independent future PAPER required')
    atomic_json(directory/'summary.json',summary)
    atomic_json(directory/'status.json',dict(stage='complete',completed_days=len(reports),ready=False,
        total_targets=summary['total_targets'],coverage_admitted=summary['coverage_admitted']))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True);a=p.parse_args()
    try:run(a.directory)
    except Exception as exc:
        atomic_json(a.directory/'last-error.json',dict(updated_ms=time.time_ns()//1000000,
            error=type(exc).__name__,reason=str(exc)[:300],ready=False))
        raise
