"""Fixed spot-long hypotheses 8/9/10. No orders, no automatic promotion."""
import json
import sqlite3
import time

import agent
from arena_backtest import simulate

RULES={'dip':'Откат после снижения', 'volume':'Откат + всплеск объёма',
       'regime':'Откат + объём + режим BTC'}


def signals(market):
    scores={k:{s:[0.]*len(bars) for s,bars in market.items()} for k in RULES}
    btc=market['BTCUSDT']
    for s,bars in market.items():
        for i in range(20,len(bars)):
            past=bars[i-20:i];current=bars[i]
            drop=max(b[2] for b in past)/current[4]-1
            amplitude=max(b[2] for b in past)/min(b[3] for b in past)-1
            rising=current[4]>bars[i-1][4]>bars[i-2][4]
            # Fixed beforehand, not retuned after viewing the final segment.
            if drop>=.006 and .006<=amplitude<=.03 and rising:
                scores['dip'][s][i]=drop
                mean_volume=sum(b[5] for b in past)/20
                if mean_volume>0 and current[5]>1.5*mean_volume:
                    scores['volume'][s][i]=drop
                    if btc[i][4]/btc[i-15][4]-1>-.002:
                        scores['regime'][s][i]=drop
    return scores


def run():
    db=sqlite3.connect('file:'+str(agent.DATA/'research.sqlite3')+'?mode=ro',uri=True)
    end=min(db.execute('SELECT max(ts) FROM bars WHERE symbol=?',(s,)).fetchone()[0] for s in agent.SYMBOLS)
    start=end-30*86400000+60000
    market={s:db.execute('SELECT ts,open,high,low,close,volume FROM bars WHERE symbol=? AND ts BETWEEN ? AND ? ORDER BY ts',(s,start,end)).fetchall() for s in agent.SYMBOLS}
    db.close();expected=list(range(start,end+1,60000))
    if any([b[0] for b in bars]!=expected for bars in market.values()):raise ValueError('History gaps')
    lots={s:agent.api('instruments-info',category='spot',symbol=s)['result']['list'][0]['lotSizeFilter'] for s in market}
    scores=signals(market);cut=len(expected)*2//3
    candidates={}
    def evaluate(rule,tp,a,b,spread):
        return simulate({s:v[a:b] for s,v in market.items()},
            {s:v[a:b] for s,v in scores[rule].items()},lots,spread,tp=tp,sl=tp*2,hold_seconds=None)
    for rule in RULES:
        for tp in (.006,.01):
            key=rule+'_'+str(tp)
            candidates[key]=dict(name=RULES[rule],tp=tp,sl=tp*2,
                validation=evaluate(rule,tp,0,cut,.0002))
    eligible=[k for k,r in candidates.items() if r['validation']['trades']>=20]
    selected=max(eligible,key=lambda k:candidates[k]['validation']['return_pct']) if eligible else None
    # Selection is complete before computing any final-segment results.
    for key,row in candidates.items():
        rule=key.rsplit('_',1)[0]
        row['test']=evaluate(rule,row['tp'],cut,len(expected),.0002)
        row['stress']=evaluate(rule,row['tp'],cut,len(expected),.0006)
    winner=candidates.get(selected)
    passed=bool(winner and winner['validation']['return_pct']>0 and winner['test']['return_pct']>0
        and winner['test']['trades']>=20 and winner['stress']['return_pct']>0)
    report=dict(created_ms=int(time.time()*1000),start_ms=start,split_ms=expected[cut],end_ms=end+60000,
        candidates=candidates,selected=selected,passes_screen=passed,auto_promoted=False,
        notes='Spot long only; partial hypothesis 8, no random short or leverage. TP/SL exits; terminal liquidation at period end. First 20 days select, last 10 evaluate. History was used in earlier research, not pristine holdout. Fee .1% and slip .05% each side; assumed spread .02% / stress .06%. One $15 account per variant across 3 symbols. Stop-first OHLC, next-open entries, 20% loss halt, current lot rules. No historical depth. Candle volume is not participant count.')
    path=agent.ARTIFACTS/'waiting_research.json';tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(report),encoding='utf-8');tmp.replace(path)
    print(json.dumps(dict(selected=selected,passes_screen=passed,results={k:{part:{f:r[part][f] for f in ('return_pct','trades','wins','mean_hold_seconds')} for part in ('validation','test','stress')} for k,r in candidates.items()})))


if __name__=='__main__':run()
