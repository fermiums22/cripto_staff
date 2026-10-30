"""Frozen earlier-period ranking experiment and explicit leave-one-symbol-out folds."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from xgboost import XGBRanker,XGBRegressor
import agent
from portfolio_market import candles,write
from portfolio_research import build_features
from portfolio_sim import simulate


def collect():
    source=json.loads((agent.ARTIFACTS/'portfolio_research.json').read_text())
    original=agent.ARTIFACTS/'portfolio'/source['run'];directory=agent.DATA/'ranker_previous';directory.mkdir(exist_ok=True)
    end=source['manifest']['start_ms']-900000;start=end-(90*96-1)*900000
    protocol=dict(source_run=source['run'],start_ms=start,end_ms=end,days=90,
        split='45 train / 15 validation / 30 test days',horizon_minutes=60,
        gaps=[0,.25,.5],seed=42,leverage=1,fee=source['fee_assumption'],
        limitations='Current-survivor universe frozen from original experiment; not point-in-time constituents')
    write(directory/'protocol.json',protocol)
    def one(s):
        path=directory/(s+'.json.gz')
        if path.exists():
            cached=json.loads(gzip.decompress(path.read_bytes()))
            if cached['start_ms']==start and cached['end_ms']==end:return s,None
        try:
            metadata=json.loads(gzip.decompress((original/(s+'.json.gz')).read_bytes()))
            if int(metadata['instrument'].get('launchTime') or 0)>start:raise ValueError('Not listed at training start')
            trade=candles(s,'kline',start,end);mark=candles(s,'mark-price-kline',start,end)
            expected=list(range(start,end+1,900000))
            if [v[0] for v in trade]!=expected or [v[0] for v in mark]!=expected:raise ValueError('Incomplete history')
            funding=[];cursor=end+899999
            while cursor>=start:
                page=agent.api('funding/history',category='linear',symbol=s,startTime=start,endTime=cursor,limit=200)['result']['list']
                funding.extend(page)
                if len(page)<200:break
                oldest=min(int(v['fundingRateTimestamp']) for v in page)
                if oldest>cursor:raise ValueError('Funding pagination stalled')
                cursor=oldest-1
            value=dict(symbol=s,start_ms=start,end_ms=end,trade=trade,mark=mark,funding=funding,
                instrument=metadata['instrument'],risk=metadata['risk'])
            path.write_bytes(gzip.compress(json.dumps(value).encode()));print('collected',s,flush=True)
            return s,None
        except Exception as exc:return s,str(exc)[:150]
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(one,source['manifest']['symbols']))
    write(directory/'manifest.json',dict(**protocol,symbols=[s for s,e in results if e is None],excluded={s:e for s,e in results if e}))
    print(json.dumps(dict(results=results)),flush=True)


def enhanced(raw,market):
    """Causal rate-of-change features; no fabricated OI/book history."""
    out={}
    for s,x in raw.items():
        lag=np.roll(x,1,axis=0);lag[0]=x[0]
        turnover=np.log1p([b[6] for b in market[s]['trade']])
        out[s]=np.c_[x,x[:,4]-lag[:,4],x[:,3]-lag[:,3],x[:,8]-lag[:,8],turnover].astype(np.float32)
    return out


def labels(market,s,i,side,fee):
    bars=market[s]['trade'];entry=bars[i+1][1];exit_price=bars[i+4][4]
    gross=side*(exit_price/entry-1);cost=2*fee+.0012
    adverse=max(0,1-min(b[3] for b in bars[i+1:i+5])/entry) if side==1 else max(0,max(b[2] for b in bars[i+1:i+5])/entry-1)
    utility=gross-cost-.25*adverse
    # Cash gets relevance 1; every realized non-positive utility gets 0.
    return 0 if utility<=0 else 2 if utility<.006 else 3 if utility<.02 else 4


def fit_ranker(market,x,symbols,train,fee):
    rows=[];y=[];qid=[];width=len(next(iter(x.values()))[0])
    for i in range(112,train-5,4):
        for s in symbols:
            for side in (-1,1):
                rows.append(np.r_[x[s][i],side,0]);y.append(labels(market,s,i,side,fee));qid.append(i)
        rows.append(np.r_[np.zeros(width),0,1]);y.append(1);qid.append(i)
    model=XGBRanker(objective='rank:ndcg',n_estimators=160,max_depth=4,learning_rate=.04,
        tree_method='hist',device='cuda',random_state=42,n_jobs=2,lambdarank_pair_method='topk',lambdarank_num_pair_per_sample=4)
    model.fit(np.asarray(rows),np.asarray(y),qid=np.asarray(qid));check_gpu(model);return model


def check_gpu(model):
    if 'cuda' not in json.loads(model.get_booster().save_config())['learner']['generic_param']['device']:
        raise RuntimeError('GPU training required')


def scores(model,x):
    model.set_params(device='cpu');n=len(next(iter(x.values())));width=len(next(iter(x.values()))[0])
    cash=float(model.predict(np.r_[np.zeros(width),0,1].reshape(1,-1))[0])
    out={s:np.column_stack([model.predict(np.c_[v,np.full(n,side),np.zeros(n)]) for side in (-1,1)]) for s,v in x.items()}
    return out,cash


def rank_signals(all_scores,cash,eligible,gap):
    n=len(next(iter(all_scores.values())));signals={s:np.zeros(n) for s in all_scores};priority={s:np.zeros(n) for s in all_scores}
    for i in range(n):
        choices=[]
        for s in eligible:
            side=int(np.argmax(all_scores[s][i]));excess=float(all_scores[s][i,side])-cash
            if excess>gap:choices.append((excess,s,-1 if side==0 else 1))
        for excess,s,side in sorted(choices,reverse=True)[:3]:signals[s][i]=side;priority[s][i]=excess
    return signals,priority


def short(r):return {k:r[k] for k in ('capital','return_pct','trades','wins','fees','max_drawdown_pct','liquidations','curve','attribution')}


def run():
    directory=agent.DATA/'ranker_previous';manifest=json.loads((directory/'manifest.json').read_text())
    market={s:json.loads(gzip.decompress((directory/(s+'.json.gz')).read_bytes())) for s in manifest['symbols']}
    if not {'BTCUSDT','ETHUSDT','SOLUSDT'}.issubset(market):raise ValueError('Missing reference instruments')
    root=agent.ARTIFACTS/'ranker'/time.strftime('%Y%m%dT%H%M%SZ',time.gmtime());root.mkdir(parents=True)
    def status(stage,**kwargs):
        write(agent.ARTIFACTS/'ranker_status.json',dict(stage=stage,run=root.name,updated_ms=int(time.time()*1000),**kwargs));print(stage,kwargs,flush=True)
    status('features');x=enhanced(build_features(market),market);symbols=sorted(market);n=len(next(iter(x.values())));train=n//2;cut=n*2//3;fee=manifest['fee']
    for s in symbols:(root/(s+'.json.gz')).write_bytes((directory/(s+'.json.gz')).read_bytes())
    def baseline(training):
        rows=[];y=[]
        for s in training:
            bars=market[s]['trade']
            for i in range(112,train-5,2):rows.append(x[s][i,:14]);y.append(bars[i+4][4]/bars[i+1][1]-1)
        m=XGBRegressor(n_estimators=200,max_depth=4,learning_rate=.03,device='cuda',tree_method='hist',random_state=42,n_jobs=2)
        m.fit(np.asarray(rows),np.asarray(y));check_gpu(m);return m
    results=[];folds=[]
    # Full cohort plus genuine leave-one-symbol-out training/validation exclusions.
    heldouts=[s for s in symbols if s not in ('BTCUSDT','ETHUSDT')]
    for fold,heldout in enumerate([None,*heldouts]):
        training=[s for s in symbols if s!=heldout];name=heldout or 'all'
        status('training',fold=fold,total=len(heldouts)+1,heldout=heldout)
        ranker=fit_ranker(market,x,training,train,fee);ranker.save_model(root/(name+'_ranker.json'))
        rs,cash=scores(ranker,x)
        validations=[]
        for gap in manifest['gaps']:
            sig,priority=rank_signals(rs,cash,training,gap)
            r=simulate(market,sig,train,cut,threshold=.5,priority=priority,fee=fee)
            validations.append(dict(gap=gap,return_pct=r['return_pct'],max_drawdown_pct=r['max_drawdown_pct'],trades=r['trades']))
        chosen=max(validations,key=lambda r:r['return_pct']-.5*r['max_drawdown_pct'])['gap']
        write(root/(name+'_selection.json'),dict(training_symbols=training,heldout=heldout,gap=chosen,validation=validations))
        model=baseline(training);model.save_model(root/(name+'_baseline.json'));model.set_params(device='cpu')
        predictions={s:model.predict(v[:,:14]) if heldout is None or s==heldout else np.zeros(n) for s,v in x.items()}
        sig,priority=rank_signals(rs,cash,[heldout] if heldout else symbols,chosen)
        a=simulate(market,predictions,cut,n,fee=fee)
        b=simulate(market,sig,cut,n,fee=fee,threshold=.5,priority=priority)
        if heldout:
            folds.append(dict(heldout=heldout,gap=chosen,baseline=short(a),ranker=short(b),training_symbols=training))
        else:
            for label,p,kw,r in [('baseline',predictions,{},a),('ranker',sig,dict(threshold=.5,priority=priority),b)]:
                stress=simulate(market,p,cut,n,fee=fee,friction=.0016,**kw)
                results.append(dict(name=label,test=short(r),stress=short(stress)))
            write(root/'main_selection.json',dict(gap=chosen,validation=validations))
    report=dict(run=root.name,created_ms=int(time.time()*1000),manifest=manifest,results=results,folds=folds,
        test_start_ms=market['BTCUSDT']['trade'][cut][0],test_end_ms=market['BTCUSDT']['trade'][-1][0]+900000,
        summary=dict(baseline_positive=sum(v['baseline']['return_pct']>0 for v in folds),ranker_positive=sum(v['ranker']['return_pct']>0 for v in folds),
            ranker_median=float(np.median([v['ranker']['return_pct'] for v in folds])),folds=len(folds)),
        limitations=['Earlier non-overlapping research holdout, not a forward live result.',
            'Current-survivor symbols and present-day trading rules still bias the universe.',
            'LOSO excludes heldout instrument from both fit and validation; BTC/ETH remain external reference features.',
            'BTC/ETH are not LOSO targets because their histories are reference features for all other instruments.',
            '60-minute labels on 15-minute bars, same approximate execution/risk engine; not tick-level scalping.',
            'Rank scores are not expected returns; cash is a learned alternative and ranking does not guarantee profitability.'])
    write(root/'report.json',report);write(agent.ARTIFACTS/'ranker_research.json',report)
    for name in ('ranker_research.py','portfolio_sim.py','portfolio_research.py'):(root/name).write_bytes(Path(name).read_bytes())
    write(root/'history_hashes.json',{s:hashlib.sha256((root/(s+'.json.gz')).read_bytes()).hexdigest() for s in symbols})
    status('complete',summary=report['summary'])
    print(json.dumps({r['name']:r['test']['return_pct'] for r in results}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--collect',action='store_true');a=p.parse_args()
    collect() if a.collect else run()
