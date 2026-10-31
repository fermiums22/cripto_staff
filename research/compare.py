"""Fixed A/B/C protocol. python -m research.compare --output STORAGE/new-run.

Historical development only; previously examined days are never called holdout.
No exchange client, production state, news, fabricated depth or live orders.
"""
import argparse
from collections import defaultdict
import csv
import gzip
import heapq
import json
from pathlib import Path
import pickle
from decimal import Decimal,ROUND_DOWN
import numpy as np
from brain_archive_stream import sha
from brain_impulse_data import atomic_json as _atomic_json
from brain_impulse_dataset import ASSETS
from research.execution import Account
from research.hypothesis_a import LeaderPolicy
from research.hypothesis_b import rule
from research.hypothesis_c import groups,fit,vector

ROOT=Path('/home/codex/projects/market-brain-storage')
SCENARIOS={'base':dict(latency_ms=1000,fee=.0006,slip=.0003),
           'slow':dict(latency_ms=5000,fee=.0006,slip=.0003),
           'stress':dict(latency_ms=2000,fee=.0008,slip=.0008)}
NAMES=['CASH','A_leader','B_rule','B_boost','B_neural','C_rule','C_boost','C_neural','Momentum','fixed_SOL','fixed_BTC']


def atomic_json(path,value):
    # NumPy comparisons produce np.bool_, which the standard encoder rejects.
    value=json.loads(json.dumps(value,default=lambda x:x.item() if isinstance(x,np.generic) else x.tolist()))
    _atomic_json(path,value)


def summarize(results):
    summary={}
    for kind in ('A','B','C'):
        entries={k:v for k,v in results.items() if k.startswith('base/'+kind+'_')}
        if not entries:continue
        best=max(entries,key=lambda k:entries[k]['net_pnl']);r=entries[best]
        summary[kind]=dict(best_development_variant=best,net_pnl=r['net_pnl'],
            verdict='no_positive_net_edge_in_this_protocol' if r['net_pnl']<=0 else 'historical_positive_only_requires_new_data',
            candidate_frozen=False,ready=False)
    return summary


def feasible(account,option,books,now):
    _,symbol,side=option;q=books.get(symbol)
    if q is None or now-q['ts']>6000:return False
    lot=account.instruments[symbol]['lotSizeFilter'];budget=min(.8*account.cash,12.)
    price=(q['asks'] if side==1 else q['bids'])[0][0]*(1+side*account.slip)
    step=Decimal(lot['qtyStep'])
    qty=float((Decimal(str(budget/(1+account.fee)/price))/step).to_integral_value(rounding=ROUND_DOWN)*step)
    return qty>=float(lot['minOrderQty']) and qty*price>=float(lot.get('minNotionalValue',0))


def tape(day):
    p=ROOT/'evolution-lab-v2/tapes'/day
    m=json.loads((p/'manifest.json').read_text())
    if sha(p/'tape.npz')!=m['sha256']:raise ValueError('Tape hash mismatch')
    with np.load(p/'tape.npz') as a:return {k:a[k] for k in a.files}


def book_events(t):
    for now,k,d in zip(t['bt'],t['bs'],t['depth']):
        yield int(now),0,dict(ts=int(now),symbol=ASSETS[int(k)],
            bids=[tuple(v) for v in d[0] if v[1]>0],asks=[tuple(v) for v in d[1] if v[1]>0])


def feature_events(t):
    for now,k,x in zip(t['ft'],t['fs'],t['fx']):
        yield int(now),1,dict(ts=int(now),symbol=ASSETS[int(k)],x=x)


def btc_events(day):
    # Derived snapshot file is immutable and hashed in protocol, BTC only here.
    path=ROOT/'archive-campaign-v1'/day/'derived/samples.jsonl.gz'
    with gzip.open(path,'rt') as f:
        for line in f:
            s=json.loads(line)
            if s['symbol']=='BTCUSDT':
                yield s['ts'],0,s
                yield s['ts'],1,s


def precompute(t,predictors):
    cache={}
    for kind,predict in predictors.items():
        xs=np.asarray([vector(x,int(k),side,kind) for x,k in zip(t['fx'],t['fs']) for side in (1,-1)])
        boost,neural=predict(xs)
        cache[kind]={ (int(now),ASSETS[int(k)]):(boost[2*i:2*i+2],neural[2*i:2*i+2])
            for i,(now,k) in enumerate(zip(t['ft'],t['fs']))}
    return cache


def choose(name,latest,scores,now):
    candidates=[]
    for symbol,(ts,x) in latest.items():
        if now-ts>6000:continue
        if name=='fixed_BTC' and symbol!='BTCUSDT':continue
        if name=='fixed_SOL' and symbol!='SOLUSDT':continue
        if name not in ('fixed_BTC',) and symbol not in ASSETS:continue
        if name in ('Momentum','fixed_SOL','fixed_BTC'):
            if abs(x[2])>0:candidates.append((abs(float(x[2])),symbol,1 if x[2]>0 else -1))
        elif name=='B_rule':
            v=rule(x)
            if v:candidates.append((v[1],symbol,v[0]))
        elif name=='C_rule':
            # Fixed cost hurdle, no parameter fit to evaluation days.
            for side in (1,-1):
                edge=side*(float(x[0])+float(x[4]))-float(x[12])-.0018
                if edge>0:candidates.append((edge,symbol,side))
        elif name[0] in scores:
            values=scores[name[0]].get((ts,symbol))
            if values is not None:
                y=values[0 if name.endswith('boost') else 1]
                candidates.extend((float(y[j]),symbol,side) for j,side in enumerate((1,-1)))
    return sorted(candidates,key=lambda a:(-a[0],a[1],-a[2]))


def replay(day,t,predictors,accounts):
    signals=json.loads((ROOT/'leader-events-v1'/f'{day}.json').read_text())['signals']
    leader=LeaderPolicy(signals);scores=precompute(t,predictors);latest={};books={};next_decision=0
    audit=dict(events=0,quotes=0,features=0,btc_min_observed_notional=None,leader_signals=len(leader.signals))
    end=int(t['bt'][-1]);previous=-1
    # Each stream is ordered. Books precede features at equal time. Never future rows.
    events=heapq.merge(book_events(t),feature_events(t),btc_events(day),key=lambda e:(e[0],e[1]))
    for now,kind,row in events:
        if now<previous:raise ValueError('Event clock regression')
        previous=now;audit['events']+=1
        closing=now>=end-180000
        if kind==0:
            audit['quotes']+=1;leader.quote(row);books[row['symbol']]=row
            if row['symbol']=='BTCUSDT':
                v=row['bids'][0][0]*float(next(iter(accounts.values())).instruments['BTCUSDT']['lotSizeFilter']['minOrderQty'])
                audit['btc_min_observed_notional']=v if audit['btc_min_observed_notional'] is None else min(v,audit['btc_min_observed_notional'])
            for a in accounts.values():
                if (a.position and a.position['symbol']==row['symbol']) or (a.pending and a.pending.get('symbol',a.position['symbol'] if a.position else None)==row['symbol']):
                    a.book(row)
        else:
            audit['features']+=1;latest[row['symbol']]=(now,row['x'])
        opportunities=leader.events(now,ASSETS)
        if opportunities and not closing:
            for key,a in accounts.items():
                if key.split('/')[1]=='A_leader':
                    opts=[o for o in opportunities if feasible(a,o,books,now)]
                    if opts:a.enter(opts[0][1],opts[0][2],now)
        if now>=next_decision:
            next_decision=now+120000
            for key,a in accounts.items():
                name=key.split('/')[1]
                if closing:
                    if a.pending and a.pending['kind']!='CLOSE':a.pending=None
                    if a.position and not a.pending:a.act(dict(kind='CLOSE'),now)
                elif name not in ('CASH','A_leader'):
                    opts=choose(name,latest,scores,now)
                    if name not in ('fixed_SOL','fixed_BTC'):opts=[o for o in opts if feasible(a,o,books,now)]
                    if opts:a.enter(opts[0][1],opts[0][2],now)
        # Avoid retaining repeated ignored action intents.
        for a in accounts.values():
            if len(a.actions)>100:a.actions.clear()
    audit.update(reaction_observations=len(leader.curves),unresolved_reactions=len(leader.pending))
    return audit,leader.curves


def main(scope=None):
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output;out.mkdir(parents=True,exist_ok=True)
    src=Path(__file__).parent
    inputs={str(f):sha(f) for f in sorted(src.glob('*.py'))}
    for day in ('2026-10-02','2026-10-03','2026-10-04','2026-10-05'):
        for rel in (f'evolution-lab-v2/tapes/{day}/tape.npz',f'evolution-lab-v2/tapes/{day}/manifest.json'):
            inputs[rel]=sha(ROOT/rel)
        if day.endswith(('04','05')):
            for rel in (f'leader-events-v1/{day}.json',f'archive-campaign-v1/{day}/derived/samples.jsonl.gz'):
                inputs[rel]=sha(ROOT/rel)
    ip=ROOT/'archive-campaign-v1/instrument-scenario.json';inputs[str(ip)]=sha(ip)
    for n in ('brain_evolution_env.py','brain_impulse_execution.py','brain_impulse_data.py','brain_factory.py'):
        inputs[n]=sha(src.parent/n)
    identity=dict(inputs=inputs,scope=scope,train=['2026-10-02'],early=['2026-10-03'],development=['2026-10-04','2026-10-05'],
        scenarios=SCENARIOS,initial_cash=15.,notional_cap=12.,leverage=1,hold_ms=120000,stop=.01,max_drawdown=.1,
        decision_interval_ms=120000,independent_evidence=False,ready=False)
    frozen=out/'protocol.json'
    if frozen.exists() and json.loads(frozen.read_text())!=identity:raise ValueError('Frozen protocol changed; use a new output directory')
    atomic_json(frozen,identity)
    completed=out/'comparison.json'
    if completed.exists():
        hashes=json.loads((out/'artifacts.json').read_text())
        for rel,h in hashes.items():
            if sha(out/rel)!=h:raise ValueError('Completed artifact changed')
        print('Verified completed experiment; no repeat',flush=True);return
    inst=json.loads(ip.read_text())['instruments'];predictors={}
    if scope!='A' and not (out/(identity['development'][-1]+'.pkl')).exists():
        train=tape('2026-10-02');early=tape('2026-10-03')
        for kind in ('B','C'):
            if scope is not None and kind!=scope:continue
            print('Preparing/training',kind,flush=True)
            predictors[kind]=fit(groups(train,inst,kind),groups(early,inst,kind),out/kind,identity)
        del train,early
    names=[n for n in NAMES if scope is None or n[0]==scope or n in ('CASH','Momentum','fixed_SOL','fixed_BTC')]
    accounts={s+'/'+n:Account(inst,**config) for s,config in SCENARIOS.items() for n in names}
    audits={};curves=[]
    for day in identity['development']:
        checkpoint=out/f'{day}.pkl'
        if checkpoint.exists():
            if sha(checkpoint)!=(out/f'{day}.sha256').read_text().strip():raise ValueError('Replay checkpoint changed')
            saved=pickle.loads(checkpoint.read_bytes())
            if saved['identity']!=identity:raise ValueError('Replay identity changed')
            accounts=saved['accounts'];audits=saved['audits'];curves=saved['curves'];continue
        print('Replay',day,flush=True)
        audit,curve=replay(day,tape(day),predictors,accounts);audits[day]=audit;curves.extend(curve)
        tmp=checkpoint.with_suffix('.part');tmp.write_bytes(pickle.dumps(dict(identity=identity,accounts=accounts,audits=audits,curves=curves)))
        tmp.replace(checkpoint);(out/f'{day}.sha256').write_text(sha(checkpoint))
    results={k:v.result() for k,v in accounts.items()}
    atomic_json(out/'leader-reactions.json',dict(observations=curves,independent_evidence=False,ready=False))
    summary=summarize(results)
    result=dict(protocol=identity,results=results,hypotheses=summary,audits=audits,ready=False,candidate=None,
        limitations=['All dates previously studied: development, not independent confirmation',
        'Archive reception clocks simulated: book +250ms, trade +350ms; actual reception unavailable',
        'Alt execution uses recorded 1s top10 book; BTC baseline recorded approximately 5s top50 snapshots',
        'Current lot-size snapshot applied historically as a scenario; no historical instrument-rule proof',
        'Depth loss is not identifiable cancellation of a particular order in aggregate book data',
        'Funding avoided by hourly-boundary exclusion; any unexpected crossing invalidates evidence',
        'Rank scores are relative, not a calibrated positive expected return; active models compared without profit claims',
        'Two development days do not support an independent confidence interval or promotion'])
    atomic_json(completed,result)
    fields=['strategy','trades','mid_gross_pnl','spread','depth_impact','slippage','fees','net_pnl','max_drawdown','average_net_pnl']
    with (out/'results.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for k,r in results.items():w.writerow(dict(strategy=k,**{n:r[n] for n in fields[1:]}))
    artifacts={str(f.relative_to(out)):sha(f) for f in out.rglob('*') if f.is_file() and f.name!='artifacts.json'}
    atomic_json(out/'artifacts.json',artifacts)
    print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
