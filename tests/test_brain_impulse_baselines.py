from pathlib import Path
import tempfile
import unittest
import numpy as np
import torch
from brain_impulse_baselines import fit,training_rows
from test_brain_impulse_models import Synthetic


class BaselineTests(unittest.TestCase):
    def test_ridge_training_only_and_tamper_guard(self):
        data=Synthetic();ids=np.arange(16)
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            predict=fit('ridge',data,ids,a,'synthetic');before=predict(data.x[:3])
            data.x[16:]=1000;data.y[16:]=1000
            other=fit('ridge',data,ids,b,'synthetic')
            np.testing.assert_equal(before,other(data.x[:3]))
            np.testing.assert_equal(before,fit('ridge',data,ids,a,'synthetic')(data.x[:3]))
            with self.assertRaises(ValueError):fit('ridge',data,ids,a,'new experiment')
            (Path(a)/'ridge.npz').write_bytes(b'broken')
            with self.assertRaises(ValueError):fit('ridge',data,ids,a,'synthetic')

    @unittest.skipUnless(torch.cuda.is_available(),'CUDA required')
    def test_cuda_boost_resume_matches_same_chunk_schedule(self):
        data=Synthetic();ids=np.arange(48)
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            full=fit('xgboost',data,ids,a,'synthetic',rounds=8)
            self.assertIsNone(fit('xgboost',data,ids,b,'synthetic',rounds=8,max_chunks=1))
            resumed=fit('xgboost',data,ids,b,'synthetic',rounds=8)
            np.testing.assert_equal(full(data.x[48:]),resumed(data.x[48:]))
            self.assertEqual(resumed(data.x[48:]).shape,(16,8))


if __name__=='__main__':unittest.main()
