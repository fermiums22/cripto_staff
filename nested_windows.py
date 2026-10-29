"""Bounded nested-position research, chronological parameter selection only."""
import json
import statistics
import time
import agent
from window_experiment import collect,simulate


def segment(data,a,b):
    return dict(data,trade=data['trade'][a:b],mark=data['mark'][a:b],
                start_ms=data['trade'][a][0],end_ms=data['trade'][b-1][0])


def summarize(runs):
    return dict(median_pct=statistics.median(r['return_pct'] for r in runs),
        worst_pct=min(r['return_pct'] for r in runs),best_pct=max(r['return_pct'] for r in runs),
        positive_runs=sum(r['return_pct']>0 for r in runs),runs=len(runs),
        median_entries=statistics.median(r['entries'] for r in runs),
        median_wins=statistics.median(r['basket_wins'] for r in runs),
        median_fees=statistics.median(r['fees'] for r in runs),
        worst_drawdown_pct=max(r['max_drawdown_pct'] for r in runs),
        liquidations=sum(r['liquidations'] for r in runs))


def run():
    data=collect();cut=len(data['trade'])*5//7
    train=segment(data,0,cut);test=segment(data,cut,len(data['trade']))
    rows=[]
    for mode in ('hedge','average'):
        for trigger in (.003,.006):
            for multiplier in (1,1.5,2):
                settings=dict(mode=mode,trigger=trigger,multiplier=multiplier)
                runs=[simulate(train,s,nested=settings) for s in range(5)]
                rows.append(dict(settings=settings,validation=summarize(runs)))
    eligible=[i for i,r in enumerate(rows) if r['validation']['median_entries']>=10]
    selected=max(eligible,key=lambda i:rows[i]['validation']['median_pct']) if eligible else None
    detailed=[]
    for i,r in enumerate(rows):
        runs=[simulate(test,s,nested=r['settings']) for s in range(100,105)]
        r['test']=summarize(runs)
        r['stress']=summarize([simulate(test,s,spread=.0006,slip=.001,nested=r['settings']) for s in range(100,105)])
        if i==selected:detailed=runs
    full=summarize([simulate(data,s,nested=rows[selected]['settings']) for s in range(5)]) if selected is not None else None
    report=dict(created_ms=int(time.time()*1000),start_ms=data['start_ms'],split_ms=test['start_ms'],end_ms=data['end_ms']+60000,
        candidates=rows,selected_index=selected,selected_runs=detailed,
        selected_full_week=full,
        notes='SOLUSDT $10 leverage10; initial window margin up to $2; max4 windows; multiplier1/1.5/2. Add after adverse .3/.6% from latest entry, at least5min, only losing basket and available margin. Hedge alternates, average repeats direction. Basket target recovers all net costs/losses plus .1% active notional; SL10% price. First5days select median with >=10 median entries, last2days test with new seeds. History already studied. Approximate cross-margin risk, current lot/MM, historical funding/mark, terminal closes. No live orders or guarantee of nonfalling capital.')
    path=agent.ARTIFACTS/'nested_windows.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(report),encoding='utf-8');tmp.replace(path)
    print(json.dumps(dict(selected_index=selected,candidates=rows)))


if __name__=='__main__':run()
