import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from brain_impulse_train import run
from brain_impulse_protocol import DAY


class TrainingIsolationTests(unittest.TestCase):
    def test_diagnostic_never_loaded_resume_and_artifact_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);output=root/'output'
            times=np.arange(0,14*DAY,300000)
            data=SimpleNamespace(times=times,ends=times+120000,input_start_ms=times-95000)
            plan=dict(start_ms=0,development=[dict(dataset='development-only')],
                diagnostic=[dict(dataset='FORBIDDEN_FINAL_DATA')],
                folds=[dict(train_end_ms=7*DAY,early_end_ms=9*DAY,score_end_ms=11*DAY),
                       dict(train_end_ms=9*DAY,early_end_ms=11*DAY,score_end_ms=14*DAY)])
            def freeze(campaign,out):
                (out/'split-plan.json').write_text(json.dumps(plan));return plan
            def fit(kind,data,train,early,folder,identity,epochs):
                self.assertLess(data.ends[train].max(),data.input_start_ms[early].min())
                for name in ('model.pt','scaler.npz','checkpoint.pt','identity.json'):(folder/name).write_text('test fixture')
                return object(),np.zeros(30),np.ones(30)
            with patch('brain_impulse_train.freeze',side_effect=freeze),patch('brain_impulse_train.Frames',return_value=data) as frames,patch('brain_impulse_train.fit',side_effect=fit) as fitter,patch('brain_impulse_train.predict',side_effect=lambda net,data,ids,*args:np.zeros((len(ids),8))):
                run(root,output);self.assertEqual(fitter.call_count,8)
                frames.assert_called_once_with(['development-only'])
                run(root,output);self.assertEqual(fitter.call_count,8)
                self.assertFalse(json.loads((output/'training-summary.json').read_text())['ready'])
                (output/'fold-0/mlp/model.pt').write_text('tampered')
                with self.assertRaises(ValueError):run(root,output)


if __name__=='__main__':unittest.main()
