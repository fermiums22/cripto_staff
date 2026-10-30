"""Audit frozen simulated executions against public trades; never infer a book."""
import bisect
import csv
import gzip
import hashlib
import io
import json
import time
import urllib.request
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
import agent
from portfolio_market import write


class HashReader:
    def __init__(self,response):self.response=response;self.digest=hashlib.sha256();self.size=0
    def read(self,size=-1):
        data=self.response.read(size);self.digest.update(data);self.size+=len(data);return data


def execution_proxy(prints,side,qty,signal_ms,latency_ms=250,participation=.1):
    """Trade participation diagnostic, NOT executable depth or guaranteed fills."""
    remaining=qty;cost=0.;last=None;available=0.
    for t,p,q,s in sorted(prints):
        if signal_ms+latency_ms<=t<=signal_ms+5000 and s==side:
            available+=q
            take=min(remaining,q*participation);cost+=take*p;remaining-=take
            if take:last=t
    return dict(filled=remaining<=max(1e-8,qty*1e-9),filled_qty=qty-remaining,
        vwap=cost/(qty-remaining) if qty>remaining else None,side_volume=available,
        completion_ms=last,participation=participation,latency_ms=latency_ms)


def run():
    source=json.loads((agent.ARTIFACTS/'portfolio_research.json').read_text())
    root=agent.ARTIFACTS/'portfolio'/source['run']
    records=[r for r in csv.DictReader((root/(source['selected']+'.csv')).open()) if r['symbol']=='QUSDT']
    events=[]
    for i,t in enumerate(records):
        for leg in ('entry','exit'):
            ts=int(t[leg+'_ms']);side=int(t['side'])*(1 if leg=='entry' else -1)
            events.append(dict(trade=i,leg=leg,ts=ts,side=side,qty=float(t['qty']),simulated=float(t[leg]),prints=[]))
    days={}
    for j,e in enumerate(events):
        for ts in (e['ts'],e['ts']+5000):
            day=datetime.fromtimestamp(ts/1000,timezone.utc).strftime('%Y-%m-%d')
            days.setdefault(day,set()).add(j)
    directory=agent.ARTIFACTS/'microstructure'/source['run'];directory.mkdir(parents=True,exist_ok=True)
    write(agent.ARTIFACTS/'microstructure_status.json',dict(stage='downloading_public_trades',days=len(days),updated_ms=int(time.time()*1000)))
    def day_job(item):
        day,ids=item;url=f'https://public.bybit.com/trading/QUSDT/QUSDT{day}.csv.gz'
        cache=directory/(day+'.json.gz')
        if cache.exists():return json.loads(gzip.decompress(cache.read_bytes()))
        indices=sorted(ids,key=lambda j:events[j]['ts']);starts=[events[j]['ts'] for j in indices]
        matches={str(j):[] for j in indices};count=0;skipped_rpi=0
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url,timeout=45) as response:
                stream=HashReader(response)
                with io.TextIOWrapper(gzip.GzipFile(fileobj=stream),encoding='utf-8') as text:
                    for row in csv.DictReader(text):
                        count+=1;ts=int(float(row['timestamp'])*1000)
                        lo=bisect.bisect_left(starts,ts-5000);hi=bisect.bisect_right(starts,ts)
                        if lo==hi:continue
                        if str(row.get('RPI','0')).lower() in ('1','true'):skipped_rpi+=1;continue
                        trade=[ts,float(row['price']),float(row['size']),1 if row['side']=='Buy' else -1]
                        for k in range(lo,hi):matches[str(indices[k])].append(trade)
                result=dict(day=day,url=url,status='complete',sha256=stream.digest.hexdigest(),bytes=stream.size,
                    public_trades=count,excluded_rpi=skipped_rpi,matches=matches)
            cache.write_bytes(gzip.compress(json.dumps(result).encode()))
            print(day,'complete',count,flush=True);return result
        except Exception as exc:
            print(day,'unavailable',type(exc).__name__,flush=True)
            return dict(day=day,url=url,status='unavailable',error=type(exc).__name__,matches={})
    with ThreadPoolExecutor(max_workers=2) as pool:archives=list(pool.map(day_job,sorted(days.items())))
    for archive in archives:
        for j,prints in archive['matches'].items():events[int(j)]['prints'].extend(prints)
    for e in events:
        e['proxy']=execution_proxy(e['prints'],e['side'],e['qty'],e['ts'])
        e['first_print_ms']=min((v[0] for v in e['prints']),default=None)
        p=e['proxy'];e['adverse_price_pct']=e['side']*(p['vwap']/e['simulated']-1)*100 if p['vwap'] else None
    fee=source['fee_assumption'];paired=[]
    for i,t in enumerate(records):
        a,b=events[2*i:2*i+2];complete=a['proxy']['filled'] and b['proxy']['filled']
        v=dict(trade=i,entry_ms=a['ts'],exit_ms=b['ts'],side=a['side'],qty=a['qty'],
            simulated_net=float(t['net']),both_legs_covered=complete,
            entry_proxy=a['proxy'],exit_proxy=b['proxy'])
        if complete:
            entry=a['proxy']['vwap'];exit_price=b['proxy']['vwap']
            v['proxy_net']=a['qty']*(a['side']*(exit_price-entry)-(entry+exit_price)*fee)+float(t['funding'])
        paired.append(v)
    matched=[v for v in paired if v['both_legs_covered']]
    report=dict(source_run=source['run'],created_ms=int(time.time()*1000),symbol='QUSDT',trades=len(records),
        events=len(events),covered_legs=sum(e['proxy']['filled'] for e in events),covered_trades=len(matched),
        simulated_net_all=sum(float(t['net']) for t in records),
        simulated_net_matched=sum(v['simulated_net'] for v in matched),proxy_net_matched=sum(v['proxy_net'] for v in matched),
        archives=[{k:v for k,v in a.items() if k!='matches'} for a in archives],
        executions=[{k:v for k,v in e.items() if k!='prints'} for e in events],paired=paired,
        limitations=['Trade prints are not historical order-book depth or spread; no guaranteed executable fills.',
            'Proxy uses 250ms delay, matching aggressor side and <=10% of observed printed volume over five seconds.',
            'Uncovered orders are not counted as zero-cost profitable executions; matched subset is not whole strategy PnL.',
            'No queue, market impact, RPI access, full-day book reconstruction or independent holdout claim.'])
    write(directory/'report.json',report);write(agent.ARTIFACTS/'qusdt_microstructure.json',report)
    write(agent.ARTIFACTS/'microstructure_status.json',dict(stage='complete',updated_ms=int(time.time()*1000)))
    print(json.dumps({k:report[k] for k in ('trades','covered_legs','covered_trades','simulated_net_all','simulated_net_matched','proxy_net_matched')}))


if __name__=='__main__':run()
