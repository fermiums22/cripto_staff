from dataclasses import replace
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import torch
from unittest.mock import patch
from brain_archive_stream import sha
from brain_impulse_evaluate import freeze_execution,plans_for_fold,run,POLICIES,predictors
from brain_impulse_models import ImpulseNet
from brain_impulse_selection import MODELS,CONTROLS,freeze_policy
from brain_impulse_protocol import DAY


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))


class EvaluationTests(unittest.TestCase):
    def test_saved_neural_loader_and_hash_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);write(out/'training-plan.json',{})
            for kind in MODELS:
                folder=out/'fold-0'/kind;folder.mkdir(parents=True)
                if kind in ('ridge','xgboost'):
                    (folder/'fixture').write_text('test');names=['fixture']
                else:
                    torch.save(ImpulseNet(kind).state_dict(),folder/'model.pt')
                    np.savez(folder/'scaler.npz',mean=np.zeros(30),std=np.ones(30));names=['model.pt','scaler.npz']
                write(folder/'result.json',dict(kind=kind,fold=0,plan_sha256=sha(out/'training-plan.json'),
                    artifacts={name:sha(folder/name) for name in names}))
            with patch('brain_impulse_evaluate.load_baseline',return_value=lambda x:np.zeros((len(x),8))):
                models=predictors(out,0)
                for kind in MODELS:
                    for i in range(8):
                        result=models[kind](dict(ts=i*5000,symbol='SOLUSDT',session='test',x=[0.]*30))
                    self.assertEqual(len(result),8)
                (out/'fold-0/mlp/model.pt').write_bytes(b'damaged')
                with self.assertRaises(ValueError):predictors(out,0)

    def test_execution_policy_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            before=freeze_execution(tmp);self.assertEqual(freeze_execution(tmp),before)
            with patch.dict(POLICIES,stress=replace(POLICIES['stress'],fee=0.)):
                with self.assertRaises(ValueError):freeze_execution(tmp)

    def test_four_scenarios_resume_and_diagnostic_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'output';out.mkdir();campaign=root/'campaign';campaign.mkdir()
            write(campaign/'instrument-scenario.json',{})
            write(campaign/'campaign-plan.json',dict(instrument_sha256=sha(campaign/'instrument-scenario.json')))
            for day in range(9,14):
                date=dt.datetime.fromtimestamp(day*86400,dt.timezone.utc).date().isoformat()
                write(campaign/date/'extraction-plan.json',dict(sources=[dict(day=date)],campaign_sha256=sha(campaign/'campaign-plan.json')))
            split=dict(start_ms=0,folds=[dict(early_end_ms=9*DAY,score_end_ms=11*DAY),dict(early_end_ms=11*DAY,score_end_ms=14*DAY)])
            write(out/'split-plan.json',split)
            training=dict(splits_sha256=sha(out/'split-plan.json'),selection_sha256=freeze_policy(out),source={})
            write(out/'training-plan.json',training);records=[]
            for fold in range(2):
                for kind in MODELS:
                    record=dict(fold=fold,kind=kind)
                    write(out/f'fold-{fold}'/kind/'result.json',record);records.append(record)
            write(out/'training-summary.json',dict(results=records))
            def fake_replay(events,models,inst,start,end,policy):
                self.assertLessEqual(end,14*DAY)
                return dict(reports={k:dict(test_fixture=True) for k in MODELS+CONTROLS})
            def fake_select(validation):
                self.assertEqual(set(validation),set(MODELS+CONTROLS))
                for value in validation.values():
                    self.assertEqual(set(value),{'base','stress'})
                    self.assertEqual([f['days'] for f in value['base']],[[9,10],[11,12,13]])
                return dict(selected_for_diagnostic='CASH',ready=False)
            with patch('brain_impulse_evaluate.predictors',return_value={}),patch('brain_impulse_evaluate.replay',side_effect=fake_replay) as replay,patch('brain_impulse_evaluate.select',side_effect=fake_select):
                run(campaign,out);self.assertEqual(replay.call_count,4)
                self.assertGreater(replay.call_args_list[1].args[-1].latency_ms,replay.call_args_list[0].args[-1].latency_ms)
                run(campaign,out);self.assertEqual(replay.call_count,4)
                split['folds'][-1]['score_end_ms']=21*DAY;write(out/'split-plan.json',split)
                with self.assertRaises(ValueError):run(campaign,out)

    def test_archive_wrong_calendar_day_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);write(p/'1970-01-02/extraction-plan.json',dict(sources=[dict(day='1970-01-03')]))
            with self.assertRaises(ValueError):plans_for_fold(p,DAY,2*DAY)


if __name__=='__main__':unittest.main()
