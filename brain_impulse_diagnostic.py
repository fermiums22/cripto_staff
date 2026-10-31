"""One selected frozen model on reserved historical diagnostic days, then stop.

Even a pass only permits a NEW prospective PAPER trial. Previously inspected
minute/candle history prevents calling this historical block independent evidence.
"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
from brain_archive_stream import sha
from brain_impulse_data import atomic_json
from brain_impulse_evaluate import run as validate,predictors,plans_for_fold,all_events,POLICIES,freeze_execution
from brain_impulse_replay import replay
from brain_impulse_selection import aggregate,paired_lower,POLICY,CONTROLS,MODELS
from brain_impulse_protocol import DAY


def assess(reports,chosen,days):
    if chosen not in MODELS:raise ValueError('Invalid diagnostic candidate')
    if len(days)!=7:raise ValueError('Require seven diagnostic calendar days')
    summaries={scenario:{name:aggregate([dict(days=days,report=report)]) for name,report in values.items()}
               for scenario,values in reports.items()}
    if set(summaries)!={'base','stress'}:raise ValueError('Missing diagnostic scenario')
    required=set(CONTROLS)|{chosen}
    if any(set(values)!=required for values in summaries.values()):raise ValueError('Unexpected diagnostic competitors')
    base=summaries['base'][chosen];stress=summaries['stress'][chosen];reasons=[];bounds={}
    for scenario,value in (('base',base),('stress',stress)):
        if value['issues']:reasons.append(scenario+'_execution_invalid')
        if value['net_pnl']<=0:reasons.append(scenario+'_nonpositive')
        if value['max_drawdown']>POLICY['max_drawdown']:reasons.append(scenario+'_drawdown')
    if base['trades']<POLICY['min_trades']:reasons.append('insufficient_trades')
    if len(base['by_symbol'])<POLICY['min_symbols']:reasons.append('insufficient_symbols')
    if base['without_best_coin']<=0 or base['best_coin_share']>POLICY['max_symbol_share']:reasons.append('coin_concentration')
    if base['best_trade_share']>POLICY['max_trade_share']:reasons.append('trade_concentration')
    for control in CONTROLS:
        if summaries['base'][control]['issues'] or summaries['stress'][control]['issues']:reasons.append('invalid_control_'+control)
        bounds[control]=paired_lower(base['daily'],summaries['base'][control]['daily'])
        if bounds[control]<=0:reasons.append('no_paired_advantage_'+control)
    return dict(chosen=chosen,rejected=bool(reasons),reasons=reasons,paired_lower_bounds=bounds,
        summaries=summaries,eligible_for_new_future_paper=not reasons,ready=False,
        independent_paper_evidence=False,live_promotion_allowed=False)


def freeze_diagnostic(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    value=dict(source_sha256=sha(Path(__file__)),policy=POLICY,days=7,model_fold=1,
               execution_sha256=freeze_execution(output),ready=False,live_promotion_allowed=False)
    path=output/'diagnostic-policy.json'
    if path.exists() and json.loads(path.read_text())!=value:raise ValueError('Diagnostic policy changed')
    if not path.exists():atomic_json(path,value)
    return sha(path)


def run(campaign,output):
    output=Path(output);campaign=Path(campaign)
    with (output/'diagnostic.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        policy_sha256=freeze_diagnostic(output)
        # Recompute selection from verified cached validation; no discretionary winner.
        decision=validate(campaign,output);chosen=decision['selected_for_diagnostic']
        if chosen=='CASH':
            atomic_json(output/'diagnostic-status.json',dict(stage='no_candidate_final_data_unopened',ready=False));return
        split=json.loads((output/'split-plan.json').read_text());start=split['start_ms']+14*DAY;end=start+7*DAY
        paths=plans_for_fold(campaign,start,end);metadata=campaign/'instrument-scenario.json'
        for path in paths:
            if json.loads(path.read_text())['campaign_sha256']!=sha(campaign/'campaign-plan.json'):
                raise ValueError('Diagnostic archive campaign mismatch')
        identity=dict(policy_sha256=policy_sha256,selection_sha256=sha(output/'validation-selection.json'),chosen=chosen,
            model_result_sha256=sha(output/'fold-1'/chosen/'result.json'),
            source_sha256=sha(Path(__file__)),execution_sha256=freeze_execution(output),
            metadata_sha256=sha(metadata),plans={str(p):sha(p) for p in paths},start_ms=start,end_ms=end)
        identity_path=output/'diagnostic-plan.json'
        if identity_path.exists() and json.loads(identity_path.read_text())!=identity:raise ValueError('Diagnostic protocol changed')
        if not identity_path.exists():atomic_json(identity_path,identity)
        inst=json.loads(metadata.read_text());inst=inst.get('instruments',inst);reports={}
        for scenario,policy in POLICIES.items():
            target=output/f'diagnostic-{scenario}.json'
            if target.exists():
                saved=json.loads(target.read_text());result=saved['result']
                if saved['sha256']!=hashlib.sha256(json.dumps(result,sort_keys=True,allow_nan=False).encode()).hexdigest():
                    raise ValueError('Diagnostic result changed')
                if result['diagnostic_plan_sha256']!=sha(identity_path):raise ValueError('Diagnostic identity mismatch')
            else:
                models=predictors(output,1);models={k:v for k,v in models.items() if k in set(CONTROLS)|{chosen}}
                atomic_json(output/'diagnostic-status.json',dict(stage='replaying',scenario=scenario,ready=False))
                result=replay(all_events(paths),models,inst,start,end,policy)
                result['diagnostic_plan_sha256']=sha(identity_path)
                atomic_json(target,dict(result=result,sha256=hashlib.sha256(json.dumps(result,sort_keys=True,allow_nan=False).encode()).hexdigest()))
            reports[scenario]=result['reports']
        result=assess(reports,chosen,list(range(start//DAY,end//DAY)))
        result['diagnostic_plan_sha256']=sha(identity_path);atomic_json(output/'diagnostic-result.json',result)
        atomic_json(output/'diagnostic-status.json',dict(stage='complete',ready=False,
            eligible_for_new_future_paper=result['eligible_for_new_future_paper']))
        return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--campaign',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.campaign,a.output)
