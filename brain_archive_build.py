"""Finite six-market, one-day development archive pilot; restart-safe by artifact."""
import argparse
import fcntl
import json
from pathlib import Path
import shutil
import time
import urllib.request
from brain_archive_probe import probe
from brain_archive_stream import extract,sha
from brain_impulse_data import atomic_json

SYMBOLS=('BTCUSDT','ETHUSDT','SOLUSDT','DOGEUSDT','XRPUSDT','BNBUSDT')
DAY='2026-10-01'


def build(directory):
    directory.mkdir(parents=True,exist_ok=True)
    lock=(directory/'build.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    path=directory/'download-plan.json'
    if path.exists():plan=json.loads(path.read_text())
    else:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));sources=[]
        for symbol in SYMBOLS:
            for kind,url in (
                ('book',f'https://quote-saver.bycsi.com/orderbook/linear/{symbol}/{DAY}_{symbol}_ob200.data.zip'),
                ('trades',f'https://public.bybit.com/trading/{symbol}/{symbol}{DAY}.csv.gz')):
                with opener.open(urllib.request.Request(url,method='HEAD'),timeout=20) as r:
                    sources.append(dict(symbol=symbol,day=DAY,kind=kind,url=url,bytes=int(r.headers['Content-Length'])))
        total=sum(s['bytes'] for s in sources)
        if total>2*1024**3 or shutil.disk_usage(directory).free-total<10*1024**3:
            raise ValueError('Pilot exceeds fixed 2GiB raw budget or 10GiB reserve')
        plan=dict(mode='historical_development_only',day=DAY,symbols=SYMBOLS,sources=sources,
            bytes=total,created_ms=time.time_ns()//1000000,
            rationale='Cross-market impulse and aggressive flow with depth execution, not a repeat candle fit',
            book_delay_ms=250,trade_delay_ms=350,ready=False)
        atomic_json(path,plan)
    sources=[]
    for symbol in SYMBOLS:
        # Reuse the already fingerprinted SOL probe without duplicating its raw data.
        raw=directory.parent/'archive-probe-20261001' if symbol=='SOLUSDT' else directory/'raw'/symbol
        atomic_json(directory/'status.json',dict(stage='downloading',symbol=symbol,ready=False))
        probe(raw,DAY,symbol)
        reports=json.loads((raw/'probe.json').read_text())['reports']
        for report in reports:
            kind='book' if report['url'].endswith('.zip') else 'trades'
            expected=next(s for s in plan['sources'] if s['symbol']==symbol and s['kind']==kind)
            if report['bytes']!=expected['bytes'] or report['url']!=expected['url']:
                raise ValueError('Archive changed after plan freeze')
            sources.append(dict(path=str(raw/report['url'].split('/')[-1]),symbol=symbol,day=DAY,
                kind=kind,sha256=report['sha256'],delay_ms=plan['book_delay_ms'] if kind=='book' else plan['trade_delay_ms']))
    extraction=dict(mode='historical_development_only',sources=sources,
        download_plan_sha256=sha(path),receipt_timing='scenario_only',ready=False)
    epath=directory/'extraction-plan.json'
    if epath.exists() and json.loads(epath.read_text())!=extraction:raise ValueError('Extraction plan changed')
    atomic_json(epath,extraction)
    atomic_json(directory/'status.json',dict(stage='extracting',ready=False))
    derived=directory/('derived-'+sha(Path(__file__).parent/'brain_archive_stream.py')[:12])
    result=extract(epath,derived)
    atomic_json(directory/'status.json',dict(stage='complete',samples=result['samples'],
        by_symbol=result['by_symbol'],derived=str(derived),ready=False,
        reason='One development day; not training or independent PAPER evidence'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True)
    build(p.parse_args().directory)
