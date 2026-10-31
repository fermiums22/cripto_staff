"""Read-only execution attribution from recorded depth tapes and completed trades.

Market gross is mid-to-mid. Old gross_pnl already includes spread/depth/slip.
No unknown funding, missing tape points or future features are manufactured.
"""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import numpy as np
from brain_archive_stream import sha
from brain_impulse_data import atomic_json
from brain_impulse_dataset import ASSETS
from brain_impulse_execution import consume


def notional(levels,qty):
    value=consume([(float(p),float(q)) for p,q in levels if q>0],qty)
    if value is None:raise ValueError('Trade quantity exceeds recorded depth')
    return value


def summarize(rows):
    wins=[r['net_pnl'] for r in rows if r['net_pnl']>0];losses=[r['net_pnl'] for r in rows if r['net_pnl']<0]
    fields=('market_gross_pnl','gross_after_execution','net_pnl','fees','spread_cost','depth_impact','slippage_cost')
    result={k:float(sum(r[k] for r in rows)) for k in fields}
    result.update(trades=len(rows),mean_win=float(np.mean(wins)) if wins else None,
        mean_loss=float(np.mean(losses)) if losses else None,win_rate=len(wins)/len(rows) if rows else None,
        mean_hold_ms=float(np.mean([r['hold_ms'] for r in rows])) if rows else None,
        mean_net_mae=float(np.mean([r['net_mae'] for r in rows])) if rows else None,
        mean_net_mfe=float(np.mean([r['net_mfe'] for r in rows])) if rows else None,
        funding=None if any(r['funding'] is None for r in rows) else 0.,
        profitable_before_costs=sum(r['market_gross_pnl']>0 for r in rows),
        cost_flipped_winners=sum(r['market_gross_pnl']>0 and r['net_pnl']<=0 for r in rows),
        max_identity_error=max((abs(r['identity_error']) for r in rows),default=0.))
    def average(values):
        values=[v for v in values if v is not None]
        return float(np.mean(values)) if values else None
    result['entry_markout_mid_pnl']={str(s):average([r['entry_markout_mid_pnl'][str(s)] for r in rows]) for s in (10,30,60)}
    result['mean_post_exit_30s_mid_pnl']=average([r['post_exit_30s_mid_pnl'] for r in rows])
    result['mean_realized_over_positive_mfe']=average([r['net_pnl']/r['net_mfe'] for r in rows if r['net_mfe']>1e-9])
    result['trades_with_path_gaps']=sum(r['path_max_gap_ms']>7000 for r in rows)
    return result


def attribute(trades,actions,tape,slip=.0003,fee=.0006):
    books={};features={}
    for i,symbol in enumerate(ASSETS):
        mask=tape['bs']==i;books[symbol]=(tape['bt'][mask],tape['depth'][mask])
        mask=tape['fs']==i;features[symbol]=(tape['ft'][mask],tape['fx'][mask])
    action_map={(a['ms'],a.get('symbol')):a for a in actions};rows=[]
    for t in trades:
        times,depth=books[t['symbol']];a=int(np.searchsorted(times,t['opened_ms']));b=int(np.searchsorted(times,t['closed_ms']))
        if b>=len(times) or times[a]!=t['opened_ms'] or times[b]!=t['closed_ms']:raise ValueError('Missing exact execution quote')
        side=t['side'];qty=t['qty'];entry=depth[a];exit=depth[b]
        mid0=float((entry[0,0,0]+entry[1,0,0])/2);mid1=float((exit[0,0,0]+exit[1,0,0])/2)
        en=notional(entry[1 if side==1 else 0],qty);ex=notional(exit[0 if side==1 else 1],qty)
        best0=float(entry[1 if side==1 else 0,0,0])*qty;best1=float(exit[0 if side==1 else 1,0,0])*qty
        market=side*(mid1-mid0)*qty
        spread=side*(best0-mid0*qty+mid1*qty-best1)
        impact=side*(en-best0+best1-ex);slippage=slip*(en+ex)
        gross=side*(ex*(1-side*slip)-en*(1+side*slip))
        if abs(gross-t['gross_pnl'])>1e-7:raise ValueError('Recorded gross does not reconcile to execution tape')
        excursions=[]
        for book in depth[a:b+1]:
            value=notional(book[0 if side==1 else 1],qty)*(1-side*slip)
            excursions.append(side*(value-en*(1+side*slip))-en*(1+side*slip)*fee-value*fee)
        ft,fx=features[t['symbol']];f=int(np.searchsorted(ft,t['signal_ms'],side='right'))-1
        if f<0 or t['signal_ms']-ft[f]>1500:regime='unknown'
        else:
            x=fx[f];regime=('high_vol' if x[5]>=.002 else 'medium_vol' if x[5]>=.0005 else 'low_vol')
            regime+='_'+('up' if x[3]>.001 else 'down' if x[3]<-.001 else 'flat')
        decision=action_map.get((t['signal_ms'],t['symbol']),{})
        marks={}
        for seconds in (10,30,60):
            target=t['opened_ms']+seconds*1000;j=int(np.searchsorted(times,target))
            marks[str(seconds)]=float(side*((depth[j,0,0,0]+depth[j,1,0,0])/2-mid0)*qty) if j<len(times) and times[j]-target<=1500 else None
        future=t['closed_ms']+30000;j=int(np.searchsorted(times,future))
        post=float(side*((depth[j,0,0,0]+depth[j,1,0,0])/2-mid1)*qty) if j<len(times) and times[j]-future<=1500 else None
        funding=0. if t['opened_ms']//3600000==t['closed_ms']//3600000 else None
        residual=market-spread-impact-slippage-t['fees']-t['net_pnl']
        if abs(residual)>1e-7:raise ValueError('Cost attribution identity failed')
        rows.append(dict(**t,market_gross_pnl=market,gross_after_execution=gross,
            spread_cost=spread,depth_impact=impact,slippage_cost=slippage,funding=funding,
            funding_basis='no_hourly_boundary_crossed' if funding==0 else 'unknown',
            identity_error=residual,hold_ms=t['closed_ms']-t['opened_ms'],
            horizon_ms=decision.get('hold_ms'),regime=regime,net_mae=min(excursions),net_mfe=max(excursions),
            entry_markout_mid_pnl=marks,post_exit_30s_mid_pnl=post,
            path_max_gap_ms=int(np.max(np.diff(times[a:b+1]))) if b>a else 0))
    return rows


def run(lab,output):
    output.mkdir(parents=True,exist_ok=True);all_rows=defaultdict(list);inputs={}
    for episode in sorted(lab.glob('train-*/*.json.gz')):
        day=episode.name[:10];tape_path=lab/'tapes'/day/'tape.npz'
        with np.load(tape_path) as f:tape={k:f[k] for k in f.files}
        with gzip.open(episode,'rt') as f:reports=json.load(f)
        expected=episode.with_name(day+'.sha256')
        if not expected.exists():continue  # Active writer has not committed checksum yet.
        digest=sha(episode)
        if digest!=expected.read_text().strip():raise ValueError('Episode checksum mismatch')
        inputs[str(episode)]=digest;inputs[str(tape_path)]=sha(tape_path)
        for agent,report in reports.items():
            rows=attribute(report['trades_detail'],report['actions'],tape)
            for row in rows:row.update(day=day,generation=episode.parent.name)
            all_rows[agent].extend(rows)
        del tape,reports
    agents={}
    for agent,rows in all_rows.items():
        groups={}
        for key in ('symbol','regime','horizon_ms','day'):
            grouped=defaultdict(list)
            for row in rows:grouped[str(row[key])].append(row)
            groups[key]={k:summarize(v) for k,v in grouped.items()}
        agents[agent]=dict(summary=summarize(rows),groups=groups)
    with gzip.open(output/'trades.json.gz','wt') as f:json.dump(all_rows,f,allow_nan=False)
    atomic_json(output/'result.json',dict(agents=agents,inputs=inputs,source_sha256=sha(Path(__file__)),
        ready=False,independent_evidence=False,limitations=['sampled one-second path, not tick-level MAE/MFE',
        'funding zero only for trades avoiding all hourly boundaries','post-exit markout is diagnostic, never a policy input']))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--lab',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.lab,a.output)
