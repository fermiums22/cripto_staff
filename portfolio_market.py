"""Public market discovery and bounded, timestamped research data collection."""
import argparse
import gzip
import json
import time
from concurrent.futures import ThreadPoolExecutor
import agent


def write(path,value):
    path.parent.mkdir(exist_ok=True,parents=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value));tmp.replace(path)


def scan():
    previous_path=agent.ARTIFACTS/'market_scan.json'
    previous=json.loads(previous_path.read_text()) if previous_path.exists() else {}
    previous_rows={v['symbol']:v for v in previous.get('rows',[])}
    instruments={};cursor='';seen=set()
    while True:
        r=agent.api('instruments-info',category='linear',limit=1000,cursor=cursor)['result']
        for v in r['list']:
            if v['quoteCoin']=='USDT' and v['contractType']=='LinearPerpetual' and v['status']=='Trading':
                instruments[v['symbol']]=v
        cursor=r.get('nextPageCursor','')
        if not cursor:break
        if cursor in seen:raise ValueError('Instrument pagination stalled')
        seen.add(cursor)
    rows=[]
    for t in agent.api('tickers',category='linear')['result']['list']:
        symbol=t['symbol']
        if symbol not in instruments:continue
        bid=float(t.get('bid1Price') or 0);ask=float(t.get('ask1Price') or 0)
        spread=(ask-bid)/((ask+bid)/2) if 0<bid<=ask else None
        turnover=float(t.get('turnover24h') or 0)
        last=float(t.get('lastPrice') or 0);prior=previous_rows.get(symbol,{})
        rows.append(dict(symbol=symbol,spread=spread,turnover=turnover,
            asset_type=instruments[symbol].get('symbolType') or 'crypto',
            last_price=last,recent_move=last/prior['last_price']-1 if prior.get('last_price') else None,
            comparison_ms=previous.get('observed_ms'),
            new_listing=int(time.time()*1000)-int(instruments[symbol].get('launchTime') or 0)<7*86400000,
            change=float(t.get('price24hPcnt') or 0),funding=float(t.get('fundingRate') or 0),
            open_interest=float(t.get('openInterestValue') or 0),
            basis=float(t['markPrice'])/float(t['indexPrice'])-1 if float(t.get('indexPrice') or 0)>0 else None,
            launch_ms=int(instruments[symbol].get('launchTime') or 0),
            eligible=not instruments[symbol].get('symbolType') and spread is not None and spread<=.001 and turnover>=3000000))
    # Resource shortlist; this snapshot is NOT a point-in-time historical universe.
    eligible=sorted((v for v in rows if v['eligible']),key=lambda v:v['turnover'],reverse=True)
    report=dict(observed_ms=int(time.time()*1000),scanned=len(rows),eligible=len(eligible),
        rows=rows,shortlist=[v['symbol'] for v in eligible[:20]])
    attention=sorted(eligible,key=lambda v:abs(v.get('recent_move') or 0),reverse=True)
    report['watchlist']=list(dict.fromkeys(['BTCUSDT','ETHUSDT',*[v['symbol'] for v in attention[:5]]]))[:5]
    write(agent.ARTIFACTS/'market_scan.json',report)
    write(agent.DATA/'portfolio_instruments.json',instruments)
    return report,instruments


def candles(symbol,kind,start,end,interval=15):
    rows={};cursor=end;step=interval*60000
    while cursor>=start:
        result=agent.api(kind,category='linear',symbol=symbol,interval=str(interval),end=cursor,limit=1000)['result']['list']
        if not result:break
        oldest=min(int(v[0]) for v in result)
        for v in result:
            ts=int(v[0])
            if start<=ts<=end:rows[ts]=[ts,*map(float,v[1:7] if kind=='kline' else v[1:5])]
        if oldest>cursor:raise ValueError('Candle cursor stalled')
        cursor=oldest-1
    return [rows[k] for k in sorted(rows)]


def collect(days=90):
    scan_result,instruments=scan();end=int(time.time()*1000)//900000*900000-900000
    start=end-(days*96-1)*900000
    symbols=list(dict.fromkeys(['BTCUSDT','ETHUSDT',*scan_result['shortlist']]))
    root=agent.DATA/'portfolio';root.mkdir(exist_ok=True)
    def one(symbol):
        status=agent.ARTIFACTS/('portfolio_collect_'+symbol+'.json')
        write(status,dict(stage='collecting',symbol=symbol))
        try:
            launch=int(instruments[symbol].get('launchTime') or 0)
            if launch>start:raise ValueError('Insufficient listing history for this fixed training cohort')
            path=root/(symbol+'.json.gz')
            if path.exists():
                cached=json.loads(gzip.decompress(path.read_bytes()))
                if cached['start_ms']==start and cached['end_ms']==end:return symbol,None
            trade=candles(symbol,'kline',start,end);mark=candles(symbol,'mark-price-kline',start,end)
            expected=list(range(start,end+1,900000))
            if [v[0] for v in trade]!=expected or [v[0] for v in mark]!=expected:
                raise ValueError('Missing candles; excluded, never filled with invented prices')
            funding=[];cursor=end+899999
            while cursor>=start:
                page=agent.api('funding/history',category='linear',symbol=symbol,startTime=start,endTime=cursor,limit=200)['result']['list']
                funding.extend(page)
                if len(page)<200:break
                oldest=min(int(v['fundingRateTimestamp']) for v in page)
                if oldest>cursor:raise ValueError('Funding cursor stalled')
                cursor=oldest-1
            risk=agent.api('risk-limit',category='linear',symbol=symbol)['result']['list']
            if not risk:raise ValueError('Missing risk tier')
            value=dict(symbol=symbol,start_ms=start,end_ms=end,trade=trade,mark=mark,
                funding=funding,instrument=instruments[symbol],risk=min(risk,key=lambda r:float(r['riskLimitValue'])))
            tmp=path.with_suffix('.tmp');tmp.write_bytes(gzip.compress(json.dumps(value).encode()));tmp.replace(path)
            write(status,dict(stage='complete',symbol=symbol,bars=len(trade)))
            return symbol,None
        except Exception as exc:
            write(status,dict(stage='excluded',symbol=symbol,error=str(exc)[:150]))
            return symbol,str(exc)[:150]
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(one,symbols))
    manifest=dict(observed_ms=scan_result['observed_ms'],start_ms=start,end_ms=end,interval_minutes=15,
        symbols=[s for s,e in results if e is None],excluded={s:e for s,e in results if e},
        bias='Current liquidity shortlist and surviving listings; not historical whole-market proof')
    write(root/'manifest.json',manifest)
    print(json.dumps(manifest),flush=True)


def observe():
    """Snapshots only: no reconstructed book and no claim of a full trade stream."""
    report,_=scan();stamp=int(time.time()*1000)
    directory=agent.DATA/'market_observations';directory.mkdir(exist_ok=True)
    for symbol in report['shortlist'][:5]:
        value=dict(observed_ms=stamp,symbol=symbol,
            book=agent.api('orderbook',category='linear',symbol=symbol,limit=50)['result'],
            trades=agent.api('recent-trade',category='linear',symbol=symbol,limit=100)['result'])
        with gzip.open(directory/(time.strftime('%Y%m%d',time.gmtime())+'.jsonl.gz'),'at') as f:
            f.write(json.dumps(value)+'\n')
    # Explicit bounded retention for public snapshots only.
    for path in directory.glob('*.jsonl.gz'):
        if path.stat().st_mtime<time.time()-14*86400:path.unlink()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--observe',action='store_true');p.add_argument('--days',type=int,default=90)
    a=p.parse_args();observe() if a.observe else collect(a.days)
