"""Raw-book BTC/ETH impulse timing experiment, historical development only.

No candle-derived book, model tuning, wallet writes or exchange orders. Fixed
leader thresholds, contemporaneous alt response strata and explicit latency arms.
"""
import argparse
from collections import defaultdict,deque
import json
import math
from pathlib import Path
from brain_archive_stream import ArchiveSource,merged,sha
from brain_impulse_data import atomic_json,execution_label
from brain_impulse_dataset import ASSETS

DELAYS=(0,1000,5000)
HORIZONS=(10000,30000,60000,120000,300000)


class Study:
    def __init__(self,instruments):
        self.instruments=instruments;self.books={};self.history=defaultdict(deque)
        self.last_sample={};self.last_trigger={};self.active=defaultdict(list)
        self.results=[];self.signals=[];self.audit=defaultdict(int);self.last_ms=-1;self.control_hours=set()

    def trigger(self,leader,now,change):
        side=1 if change>=0 else -1
        signal=dict(leader=leader,signal_ms=now,leader_return=change,side=side)
        self.signals.append(signal)
        for symbol in ASSETS:
            hist=self.history[symbol]
            past=next((r for r in reversed(hist) if r[0]<=now-1000),None)
            fresh=bool(hist and now-hist[-1][0]<=1500)
            if not fresh or past is None or now-1000-past[0]>300:
                self.audit['signal_without_alt_history']+=1;continue
            alt_change=math.log(hist[-1][1]/past[1]);ratio=alt_change/change if change else 0.
            stratum='lagging' if ratio<=.25 else 'already_moving'
            for delay in DELAYS:
                horizons=[h for h in HORIZONS if now//3600000==(now+2*delay+h+3000)//3600000]
                if not horizons:self.audit['funding_boundary']+=1;continue
                self.active[symbol].append(dict(**signal,delay_ms=delay,symbol=symbol,
                    alt_return=alt_change,stratum=stratum,eligible=now+delay,entry=None,horizons=horizons))

    def invalidate(self,symbol,reason):
        self.books.pop(symbol,None);self.history[symbol].clear();self.last_sample.pop(symbol,None)
        self.audit[reason]+=1
        self.audit['discarded_incomplete_arms']+=len(self.active[symbol]);self.active[symbol]=[]

    def ingest(self,raw):
        now=int(raw['received_ms']);m=raw['message'];symbol=m['topic'].split('.')[-1]
        if now<self.last_ms:raise ValueError('Raw receive-clock regression')
        self.last_ms=now
        if not 0<=now-int(m['ts'])<=1500:self.invalidate(symbol,'stale_book');return
        d=m['data'];reset=m.get('type')=='snapshot' or d['u']==1
        if reset:
            self.invalidate(symbol,'snapshot');self.books[symbol]=dict(b={},a={},seq=-1,u=-1,received_ms=now)
        if symbol not in self.books:return
        b=self.books[symbol]
        if not reset and (d['seq']<=b['seq'] or d['u']<=b['u']):self.invalidate(symbol,'regressing_update');return
        if now-b['received_ms']>7000:self.invalidate(symbol,'book_gap');return
        for key in ('a','b'):
            for price,qty in d.get(key,[]):
                price,qty=float(price),float(qty)
                if not math.isfinite(price*qty) or price<=0 or qty<0:self.invalidate(symbol,'invalid_level');return
                if qty:b[key][price]=qty
                else:b[key].pop(price,None)
        b.update(seq=d['seq'],u=d['u'],received_ms=now)
        if not b['a'] or not b['b']:self.invalidate(symbol,'empty_book');return
        due=self.active[symbol]
        need=any((p['entry'] is None and now>=p['eligible']) or (p['entry'] is not None and now>=p['entry']['ts']+p['horizons'][0]+p['delay_ms']) for p in due)
        if need:
            quote=dict(ts=now,bids=sorted(b['b'].items(),reverse=True)[:50],asks=sorted(b['a'].items())[:50])
            if quote['bids'][0][0]>=quote['asks'][0][0]:self.invalidate(symbol,'crossed_book');return
            keep=[]
            for arm in due:
                if arm['entry'] is None and now>=arm['eligible']:
                    if now-arm['eligible']>1500:self.audit['late_entry']+=1;continue
                    arm['entry']=quote
                if arm['entry'] is not None:
                    while arm['horizons'] and now>=arm['entry']['ts']+arm['horizons'][0]+arm['delay_ms']:
                        h=arm['horizons'].pop(0);expected=arm['entry']['ts']+h+arm['delay_ms']
                        if now-expected>1500 or now//3600000!=arm['signal_ms']//3600000:
                            self.audit['late_exit_or_funding']+=1;continue
                        for direction in (arm['side'],-arm['side']):
                            result=execution_label(arm['entry'],quote,self.instruments[symbol]['lotSizeFilter'],direction,notional=25.)
                            if result is None:self.audit['quantity_or_depth']+=1;continue
                            lot=self.instruments[symbol]['lotSizeFilter']
                            if result['qty']>float(lot.get('maxMktOrderQty',lot.get('maxOrderQty','inf'))):self.audit['max_quantity']+=1;continue
                            self.results.append(dict(**{k:v for k,v in arm.items() if k not in ('entry','horizons','eligible','side')},
                                side=direction,alignment='aligned' if direction==arm['side'] else 'opposite',horizon_ms=h,
                                entry_ms=arm['entry']['ts'],exit_ms=now,actual_entry_delay_ms=arm['entry']['ts']-arm['signal_ms'],**result))
                if arm['horizons']:keep.append(arm)
            self.active[symbol]=keep
        if now-self.last_sample.get(symbol,-10**15)<100:return
        bid,ask=max(b['b']),min(b['a'])
        if bid>=ask:self.invalidate(symbol,'crossed_book');return
        self.last_sample[symbol]=now;mid=(bid+ask)/2;hist=self.history[symbol];hist.append((now,mid))
        while hist and hist[0][0]<now-2500:hist.popleft()
        if symbol in ('BTCUSDT','ETHUSDT'):
            past=next((r for r in reversed(hist) if r[0]<=now-1000),None)
            if past and now-1000-past[0]<=300:
                change=math.log(mid/past[1])
                if abs(change)>=.001 and now-self.last_trigger.get(symbol,-10**15)>=180000:
                    self.last_trigger[symbol]=now;self.trigger(symbol,now,change)
        hour=now//3600000
        if symbol=='BTCUSDT' and hour not in self.control_hours and 600000<=now%3600000<601000:
            self.control_hours.add(hour);self.trigger('clock_control',now,.001)


def day(plan,instruments):
    specs=json.loads(plan.read_text());sources=[]
    for s in specs['sources']:
        if s['kind']!='book':continue
        path=Path(s['path'])
        if sha(path)!=s['sha256']:raise ValueError('Raw book source changed')
        sources.append(ArchiveSource(path,s['symbol'],s['day'],s['kind'],s['delay_ms']))
    study=Study(instruments)
    for row in merged(sources):study.ingest(row)
    if not all(s.stats['crc_complete'] for s in sources):raise ValueError('Incomplete book archive')
    return dict(signals=study.signals,outcomes=study.results,audit=dict(study.audit),
        unresolved_arms=sum(map(len,study.active.values())),ready=False)


def run(campaign,output):
    output.mkdir(parents=True,exist_ok=True);days=[f'2026-10-{n:02d}' for n in range(2,6)]
    sources=('brain_leader_events.py','brain_archive_stream.py','brain_impulse_data.py')
    plan=dict(days=days,source={n:sha(Path(__file__).parent/n) for n in sources},leader_threshold=.001,
        leader_lookback_ms=1000,cooldown_ms=180000,delays=DELAYS,horizons=HORIZONS,notional=25.,
        inputs={d:sha(campaign/d/'extraction-plan.json') for d in days},
        instruments_sha256=sha(campaign/'instrument-scenario.json'),ready=False,
        mode='historical_development_only',receipt_clock='simulated public archive receive delay')
    # JSON roundtrip makes tuple representation identical on resume.
    plan=json.loads(json.dumps(plan));p=output/'plan.json'
    if p.exists() and json.loads(p.read_text())!=plan:raise ValueError('Leader timing plan changed')
    if not p.exists():atomic_json(p,plan)
    snapshot=output/'source';snapshot.mkdir(exist_ok=True)
    for name,h in plan['source'].items():
        target=snapshot/name
        if not target.exists():target.write_bytes((Path(__file__).parent/name).read_bytes())
        if sha(target)!=h:raise ValueError('Frozen source changed')
    instruments=json.loads((campaign/'instrument-scenario.json').read_text());instruments=instruments.get('instruments',instruments)
    for d in days:
        target=output/(d+'.json')
        digest=output/(d+'.sha256')
        if target.exists() and digest.exists():
            if sha(target)!=digest.read_text().strip():raise ValueError('Cached day changed')
            if json.loads(target.read_text())['plan_sha256']!=sha(p):raise ValueError('Day plan changed')
            continue
        atomic_json(output/'status.json',dict(stage='raw_book_replay',day=d,ready=False))
        result=day(campaign/d/'extraction-plan.json',instruments);result['plan_sha256']=sha(p);atomic_json(target,result);digest.write_text(sha(target))
    atomic_json(output/'status.json',dict(stage='complete',ready=False,independent_evidence=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--campaign',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.campaign,a.output)
