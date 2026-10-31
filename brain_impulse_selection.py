"""Validation-only rejection gate. Passing permits diagnostics, never live trading.

Input is completed event-depth replay, not regression scores or target labels.
Bootstrap blocks are calendar days; paired comparisons include inactive days.
Thresholds are fixed before inspecting any trained candidate's validation PnL.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
from brain_archive_stream import sha
from brain_impulse_data import atomic_json

MODELS=('ridge','xgboost','mlp','tcn','gru','moe')
CONTROLS=('cash','momentum','leadlag_flow')
POLICY=dict(min_days=5,min_trades=100,min_symbols=3,max_drawdown=.10,
            max_symbol_share=.60,max_trade_share=.20,bootstrap_repeats=20000,
            block_days=2,family_alpha=.05,seed=7301)


def freeze_policy(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    value=dict(policy=POLICY,models=list(MODELS),controls=list(CONTROLS),
               source_sha256=sha(Path(__file__)),ready=False,live_promotion_allowed=False)
    path=directory/'selection-policy.json'
    if path.exists() and json.loads(path.read_text())!=value:
        raise ValueError('Frozen selection policy changed')
    if not path.exists():atomic_json(path,value)
    return sha(path)


def paired_lower(a,b):
    """Circular two-day moving blocks, multiplicity-adjusted one-sided bound."""
    a,b=np.asarray(a,dtype=float),np.asarray(b,dtype=float)
    if a.shape!=b.shape or a.ndim!=1 or len(a)<POLICY['min_days'] or not np.isfinite([a,b]).all():
        raise ValueError('Insufficient or invalid paired calendar observations')
    diff=a-b;n=len(diff);rng=np.random.default_rng(POLICY['seed'])
    starts=rng.integers(0,n,size=(POLICY['bootstrap_repeats'],(n+1)//2))
    idx=np.stack((starts,(starts+1)%n),axis=-1).reshape(len(starts),-1)[:,:n]
    means=diff[idx].mean(axis=1)
    return float(np.quantile(means,POLICY['family_alpha']/(len(MODELS)*len(CONTROLS))))


def aggregate(folds):
    daily=[];trades=[];dates=[];issues=[];drawdown=0.;pnls=[]
    if not folds:raise ValueError('Missing validation folds')
    for fold in folds:
        report=fold['report'];days=fold['days'];values=report['daily_pnl']
        if len(days)!=len(values) or any(b!=a+1 for a,b in zip(days,days[1:])):
            raise ValueError('Invalid calendar alignment')
        if dates and days and days[0]<=dates[-1]:raise ValueError('Overlapping or unordered folds')
        if not report['execution_valid'] or report['evidence_issues']:issues.append('invalid_execution')
        if not np.isfinite([*values,report['mark_to_market_drawdown'],report['fees'],report['net_pnl']]).all():
            raise ValueError('Nonfinite replay metrics')
        if report['fees']<0 or abs(sum(values)-report['net_pnl'])>1e-8:raise ValueError('Invalid replay totals')
        details=report['trades_detail']
        if len(details)!=report['trades'] or abs(sum(t['net_pnl'] for t in details)-report['net_pnl'])>1e-8:
            raise ValueError('Trade journal does not reconcile')
        if abs(sum(t['fees'] for t in details)-report['fees'])>1e-8:raise ValueError('Trade fees do not reconcile')
        for trade in details:
            day=trade['closed_ms']//86400000
            if day not in days:raise ValueError('Trade outside declared validation days')
        if any(abs(sum(t['net_pnl'] for t in details if t['closed_ms']//86400000==day)-value)>1e-8
               for day,value in zip(days,values)):raise ValueError('Daily journal mismatch')
        daily.extend(values);dates.extend(days);trades.extend(details)
        pnls.append(report['net_pnl']);drawdown=max(drawdown,report['mark_to_market_drawdown'])
    coins={}
    for trade in trades:coins[trade['symbol']]=coins.get(trade['symbol'],0.)+trade['net_pnl']
    gains=[max(0,t['net_pnl']) for t in trades];positive=sum(gains)
    coin_gains=sum(max(0,v) for v in coins.values());total=sum(daily)
    return dict(days=dates,daily=daily,trades=len(trades),net_pnl=total,fold_pnl=pnls,
        max_drawdown=drawdown,by_symbol=coins,issues=issues,
        without_best_coin=total-max(coins.values(),default=0),
        best_coin_share=max(coins.values(),default=0)/coin_gains if coin_gains else 1.,
        best_trade_share=max(gains,default=0)/positive if positive else 1.)


def select(validation):
    """Require the fixed entire family and both execution scenarios; no cherry-picking."""
    names=set(MODELS+CONTROLS)
    if set(validation)!=names:raise ValueError('Missing or unexpected competitors')
    summaries={};reference=None
    for name in MODELS+CONTROLS:
        if set(validation[name])!={'base','stress'}:raise ValueError('Require base and stress scenarios')
        summaries[name]={scenario:aggregate(folds) for scenario,folds in validation[name].items()}
        for summary in summaries[name].values():
            if reference is None:reference=summary['days']
            if summary['days']!=reference:raise ValueError('Unpaired validation dates')
    results={};passing=[]
    for name in MODELS:
        base,stress=summaries[name]['base'],summaries[name]['stress'];reasons=[];bounds={}
        if len(reference)<POLICY['min_days']:reasons.append('insufficient_calendar_days')
        for scenario,value in (('base',base),('stress',stress)):
            if value['issues']:reasons.append(scenario+'_execution_invalid')
            if value['net_pnl']<=0 or any(p<=0 for p in value['fold_pnl']):reasons.append(scenario+'_nonpositive_fold')
            if value['max_drawdown']>POLICY['max_drawdown']:reasons.append(scenario+'_drawdown')
        if base['trades']<POLICY['min_trades']:reasons.append('insufficient_trades')
        if len(base['by_symbol'])<POLICY['min_symbols']:reasons.append('insufficient_symbols')
        if base['without_best_coin']<=0 or base['best_coin_share']>POLICY['max_symbol_share']:reasons.append('coin_concentration')
        if base['best_trade_share']>POLICY['max_trade_share']:reasons.append('trade_concentration')
        if len(reference)>=POLICY['min_days']:
            for control in CONTROLS:
                baseline=summaries[control]['base']
                if baseline['issues']:reasons.append('invalid_control_'+control)
                bounds[control]=paired_lower(base['daily'],baseline['daily'])
                if bounds[control]<=0:reasons.append('no_paired_advantage_'+control)
        result=dict(rejected=bool(reasons),reasons=reasons,paired_lower_bounds=bounds,summary=base,stress=stress)
        results[name]=result
        if not reasons:passing.append((min(bounds.values()),name))
    passing.sort(key=lambda x:(-x[0],x[1]))
    encoded=json.dumps(validation,sort_keys=True,allow_nan=False).encode()
    return dict(selected_for_diagnostic=passing[0][1] if passing else 'CASH',results=results,
        input_sha256=hashlib.sha256(encoded).hexdigest(),policy=POLICY,ready=False,
        independent_paper_evidence=False,live_promotion_allowed=False)
