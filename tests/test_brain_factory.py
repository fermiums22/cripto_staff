import tempfile
import pathlib
import unittest
import numpy as np
import torch
from brain_factory import split_indices, windows, replay, LENGTH, train_neural
from brain_factory_models import SequenceModel
from brain_research import SYMBOLS, STEP


class FactoryTests(unittest.TestCase):
    def test_split_purges_targets_and_sequence_context(self):
        for horizon in (1,4):
            train,early,selection=split_indices(1000,horizon)
            self.assertLess(train[-1]+horizon+1,early[0]-LENGTH+1)
            self.assertLess(early[-1]+horizon+1,selection[0]-LENGTH+1)

    def test_future_mutation_does_not_change_input(self):
        z=np.random.default_rng(1).normal(size=(100,6,8)).astype('float32')
        before=windows(z,np.array([40,50]));z[51:]*=100
        np.testing.assert_array_equal(before,windows(z,np.array([40,50])))

    def test_all_architectures_use_cross_market_sequence(self):
        x=torch.randn(2,LENGTH,6,8)
        for kind in ('mlp','tcn','gru','lstm','transformer','moe'):
            net=SequenceModel(kind); result=net(x)
            self.assertEqual(tuple(result.shape),(2,6))
            result.square().mean().backward()
            self.assertTrue(all(torch.isfinite(p.grad).all() for p in net.parameters() if p.grad is not None))

    @unittest.skipUnless(torch.cuda.is_available(),'requires CUDA training environment')
    def test_all_cuda_architectures_mixed_precision_backward(self):
        x=torch.randn(2,LENGTH,6,8,device='cuda')
        for kind in ('mlp','tcn','gru','lstm','transformer','moe'):
            net=SequenceModel(kind).cuda()
            with torch.autocast('cuda',dtype=torch.float16):
                loss=net(x).float().square().mean()
            loss.backward()
            self.assertTrue(torch.isfinite(loss))
            self.assertTrue(all(torch.isfinite(p.grad).all() for p in net.parameters() if p.grad is not None))

    def test_wallet_costs_and_nonoverlap(self):
        a=np.ones((40,6,6))*100;ts=np.arange(40)*STEP
        meta={s:dict(instrument={'lotSizeFilter':{'qtyStep':'.001','minOrderQty':'.001',
                            'minNotionalValue':'5'}},funding=[]) for s in SYMBOLS}
        ids=np.arange(17,35);pred=np.ones((len(ids),6))*.01
        result=replay(pred,a,ts,meta,ids,4)
        self.assertEqual(result['trades'],4)
        self.assertLess(result['net_pnl'],0)
        self.assertAlmostEqual(result['net_pnl'],-result['costs'])
        cash=replay(np.zeros_like(pred),a,ts,meta,ids,4)
        self.assertEqual(cash['final_equity'],15.)
        self.assertEqual(cash['trades'],0)

    @unittest.skipUnless(torch.cuda.is_available(),'requires CUDA training environment')
    def test_checkpoint_resume_matches_continuous_training(self):
        rng=np.random.default_rng(2)
        z=rng.normal(size=(100,6,8)).astype('float32')
        y=rng.normal(0,.001,size=(100,6)).astype('float32')
        train=np.arange(16,40);early=np.arange(60,80)
        with tempfile.TemporaryDirectory() as one,tempfile.TemporaryDirectory() as two:
            continuous=train_neural('mlp',z,y,train,early,pathlib.Path(one),'test',2)
            train_neural('mlp',z,y,train,early,pathlib.Path(two),'test',1)
            resumed=train_neural('mlp',z,y,train,early,pathlib.Path(two),'test',2)
            for name,value in continuous.state_dict().items():
                torch.testing.assert_close(value,resumed.state_dict()[name],rtol=0,atol=0)
            with self.assertRaises(ValueError):
                train_neural('mlp',z,y,train,early,pathlib.Path(two),'modified',3)


if __name__=='__main__':unittest.main()
