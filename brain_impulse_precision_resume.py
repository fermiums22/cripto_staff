"""Explicit, copy-only lineage for the FP16 overflow runtime correction.

Preserves the failed experiment verbatim. No selection metrics are read or
thresholds changed. All model/optimizer/RNG tensors must survive copy exactly.
"""
import argparse
import json
from pathlib import Path
import shutil
import torch
from brain_archive_stream import sha
from brain_impulse_data import atomic_json
from brain_impulse_splits import freeze
from brain_impulse_selection import freeze_policy
from brain_impulse_evaluate import freeze_execution
from brain_impulse_diagnostic import freeze_diagnostic
from brain_impulse_train import CODE,KINDS


def equal(a,b):
    if isinstance(a,torch.Tensor):return isinstance(b,torch.Tensor) and torch.equal(a,b)
    if isinstance(a,dict):return isinstance(b,dict) and a.keys()==b.keys() and all(equal(a[k],b[k]) for k in a)
    if isinstance(a,(list,tuple)):return type(a)==type(b) and len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
    return a==b


def migrate(old,new,campaign):
    old,new,campaign=map(Path,(old,new,campaign));root=Path(__file__).resolve().parent
    if old.resolve()==new.resolve() or (new.exists() and any(new.iterdir())):raise ValueError('Destination must be new and empty')
    if not (old/'runtime-failure.json').exists():raise ValueError('Require documented failed runtime')
    prior=json.loads((old/'training-plan.json').read_text());current={n:sha(root/n) for n in CODE}
    changed={n for n in current if current[n]!=prior['source'].get(n)}
    if changed!={'brain_impulse_models.py'}:raise ValueError('Migration only permits the documented model runtime correction')
    for n,h in prior['source'].items():
        if sha(old/'runtime-failed-source'/n)!=h:raise ValueError('Original source snapshot changed')
    new.mkdir(parents=True,exist_ok=True);selection=freeze_policy(new);freeze(campaign,new)
    if prior['splits_sha256']!=sha(new/'split-plan.json') or prior['selection_sha256']!=selection:
        raise ValueError('Data splits or selection gates changed')
    freeze_execution(new);freeze_diagnostic(new)
    plan=dict(splits_sha256=sha(new/'split-plan.json'),selection_sha256=selection,source=current,
              kinds=KINDS,max_epochs=25,ready=False,stage='competition_training_only')
    atomic_json(new/'training-plan.json',plan);old_plan=sha(old/'training-plan.json');new_plan=sha(new/'training-plan.json')
    records=[]
    for source in sorted(old.glob('fold-*/*')):
        if not source.is_dir():continue
        fold=int(source.parent.name.split('-')[-1]);kind=source.name
        if fold not in (0,1) or kind not in KINDS:raise ValueError('Unexpected source model')
        target=new/source.relative_to(old);target.parent.mkdir(exist_ok=True)
        result=source/'result.json'
        if result.exists():
            value=json.loads(result.read_text())
            if value['plan_sha256']!=old_plan:raise ValueError('Source result plan changed')
            for n,h in value['artifacts'].items():
                if sha(source/n)!=h:raise ValueError('Source artifact changed')
        shutil.copytree(source,target)
        identity_name='baseline-identity.json' if kind in ('ridge','xgboost') else 'identity.json'
        before=json.loads((source/identity_name).read_text())
        if before['experiment_id']!=f'{old_plan}:{fold}:{kind}':raise ValueError('Unexpected source experiment identity')
        after=dict(before,experiment_id=f'{new_plan}:{fold}:{kind}')
        if kind not in ('ridge','xgboost'):after['code_sha256']=current['brain_impulse_models.py']
        atomic_json(target/identity_name,after)
        checkpoint=source/'checkpoint.pt';checkpoint_pair=None
        if checkpoint.exists():
            saved=torch.load(checkpoint,weights_only=True,map_location='cpu')
            if saved['identity']!=before:raise ValueError('Checkpoint identity differs from manifest')
            revised=dict(saved,identity=after);torch.save(revised,target/'checkpoint.pt')
            checked=torch.load(target/'checkpoint.pt',weights_only=True,map_location='cpu')
            if not all(equal(saved[k],checked[k]) for k in saved if k!='identity'):
                raise ValueError('Training state changed during precision migration')
            checkpoint_pair=dict(old_sha256=sha(checkpoint),new_sha256=sha(target/'checkpoint.pt'),epoch=saved['epoch'])
        if result.exists():
            value['plan_sha256']=new_plan
            value['artifacts']={n:sha(target/n) for n in value['artifacts']}
            atomic_json(target/'result.json',value)
        records.append(dict(fold=fold,kind=kind,completed=result.exists(),checkpoint=checkpoint_pair,
                            old_identity_sha256=sha(source/identity_name),new_identity_sha256=sha(target/identity_name)))
    report=dict(reason='Bounded AMP loss-scale backoff; no invalid optimizer steps, no changed hypothesis',
        old_directory=str(old),old_plan_sha256=old_plan,new_plan_sha256=new_plan,changed_sources=sorted(changed),
        preserved_training_state=True,records=records,ready=False,source_sha256=sha(Path(__file__)))
    atomic_json(new/'precision-resume-lineage.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--old',type=Path,required=True);p.add_argument('--new',type=Path,required=True)
    p.add_argument('--campaign',type=Path,required=True);a=p.parse_args();print(json.dumps(migrate(a.old,a.new,a.campaign)))
