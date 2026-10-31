from pathlib import Path
import tempfile
import unittest
import numpy as np
import torch
from brain_impulse_models import ImpulseNet,fit,scale_train,validate_split


class Synthetic:
    def __init__(self):
        rng=np.random.default_rng(9);self.x=rng.normal(size=(64,8,30)).astype('float32')
        self.y=rng.normal(0,.001,size=(64,8)).astype('float32')
        self.times=np.arange(64)*10000;self.ends=self.times+120000;self.input_start_ms=self.times-95000
    def batch(self,ids):return self.x[ids],self.y[ids]


class ModelTests(unittest.TestCase):
    def test_scaler_never_reads_validation(self):
        data=Synthetic();train=np.arange(16);before=scale_train(data,train)
        data.x[40:]*=100000
        after=scale_train(data,train)
        for a,b in zip(before,after):np.testing.assert_equal(a,b)
        validate_split(data,train,np.arange(40,60))
        with self.assertRaises(ValueError):validate_split(data,train,np.arange(20,30))

    @unittest.skipUnless(torch.cuda.is_available(),'CUDA runtime required')
    def test_eight_cost_outputs_all_architectures_backward(self):
        for kind in ('mlp','tcn','gru','moe'):
            model=ImpulseNet(kind).cuda()
            with torch.autocast('cuda',dtype=torch.float16):y=model(torch.randn(4,8,30,device='cuda'))
            self.assertEqual(tuple(y.shape),(4,8));y.float().square().mean().backward()
            self.assertTrue(all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters()))

    @unittest.skipUnless(torch.cuda.is_available(),'CUDA runtime required')
    def test_optimizer_resume_matches_uninterrupted(self):
        data=Synthetic();train=np.arange(16);val=np.arange(40,60)
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            full,_,_=fit('mlp',data,train,val,Path(a),'synthetic',2)
            fit('mlp',data,train,val,Path(b),'synthetic',1)
            resumed,_,_=fit('mlp',data,train,val,Path(b),'synthetic',2)
            for name,p in full.state_dict().items():torch.testing.assert_close(p,resumed.state_dict()[name],rtol=0,atol=0)
            with self.assertRaises(ValueError):fit('mlp',data,train,val,Path(b),'changed-protocol',3)


if __name__=='__main__':unittest.main()
