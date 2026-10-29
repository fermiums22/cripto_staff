"""Published entry-rule benchmark with explicitly local execution assumptions."""
import json
import sqlite3
import time
import agent
from arena_backtest import simulate
from sourced_rules import NAMES,aggregate,entry_scores


def run():
    db=sqlite3.connect('file:'+str(agent.DATA/'research.sqlite3')+'?mode=ro',uri=True)
    end=min(db.execute('SELECT max(ts) FROM bars WHERE symbol=?',(s,)).fetchone()[0] for s in agent.SYMBOLS)
    start=end-30*86400000+60000
    market={s:db.execute('SELECT ts,open,high,low,close,volume FROM bars WHERE symbol=? AND ts BETWEEN ? AND ? ORDER BY ts',(s,start-86400000,end)).fetchall() for s in agent.SYMBOLS}
    db.close()
    expected=list(range(start-86400000,end+1,60000))
    if any([b[0] for b in bars]!=expected for bars in market.values()):raise ValueError('Missing minutes')
    scores={k:{} for k in NAMES}
    for s,bars in market.items():
        candles=aggregate(bars);raw=entry_scores([b[4] for b in candles])
        for k in NAMES:
            by_close={b[0]+120000:raw[k][i] for i,b in enumerate(candles)}
            scores[k][s]=[by_close.get(b[0],0) for b in bars if b[0]>=start]
        market[s]=[b for b in bars if b[0]>=start]
    lots={s:agent.api('instruments-info',category='spot',symbol=s)['result']['list'][0]['lotSizeFilter'] for s in market}
    cut=len(market['BTCUSDT'])*2//3;rows={}
    for k,name in NAMES.items():
        def test(a,b,spread):
            return simulate({s:v[a:b] for s,v in market.items()},{s:v[a:b] for s,v in scores[k].items()},lots,spread,tp=.01,sl=.02,hold_seconds=None)
        rows[k]=dict(name=name,validation=test(0,cut,.0002),test=test(cut,len(market['BTCUSDT']),.0002),stress=test(cut,len(market['BTCUSDT']),.0006))
    report=dict(created_ms=int(time.time()*1000),start_ms=start,end_ms=end+60000,split_ms=market['BTCUSDT'][cut][0],
        candidates=rows,notes='Independent long-only entry adaptations, NOT original bot performance. 3m BB100 sigma2; MACD21/42/9. Local TP1% SL2%, no timer, terminal liquidation. Minute execution, next-open, stop-first; spot fee .1% and slip .05% per side, spread .02% / .06%. Shared $15 per strategy across BTC/ETH/SOL. Previously inspected history, no pristine holdout. No automatic promotion.')
    path=agent.ARTIFACTS/'sourced_research.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(report),encoding='utf-8');tmp.replace(path)
    print(json.dumps({k:{p:{f:r[p][f] for f in ('return_pct','trades','wins')} for p in ('validation','test','stress')} for k,r in rows.items()}))


if __name__=='__main__':run()
