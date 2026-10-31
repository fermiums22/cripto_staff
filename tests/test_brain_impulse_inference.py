import unittest
import numpy as np
import torch
from brain_impulse_inference import SequenceSignals,neural_predictor
from brain_impulse_models import ImpulseNet


def row(t,symbol='SOLUSDT',session='a'):
    return dict(ts=t,symbol=symbol,session=session,x=[float(t)]*30)


class InferenceTests(unittest.TestCase):
    def test_exact_past_windows_and_output_mapping(self):
        seen=[]
        def predict(x):seen.append(x.copy());return np.arange(8,dtype=float)[None,:]/1000
        model=SequenceSignals(predict)
        for i in range(7):self.assertEqual(model(row(i*5000)),[])
        signals=model(row(35000))
        np.testing.assert_equal(seen[0][0,:,0],np.arange(8)*5000)
        self.assertEqual([(s['horizon_ms'],s['side']) for s in signals],[(h,s) for h in (10000,30000,60000,120000) for s in (1,-1)])
        self.assertEqual(signals[-1]['expected_net_return'],.007)
        self.assertTrue(all(s['observed_ms']==35000 for s in signals))

    def test_symbol_session_gap_and_reservation_isolation(self):
        calls=[];model=SequenceSignals(lambda x:calls.append(x) or np.zeros((1,8)),reservations=[(100000,200000)])
        for i in range(8):self.assertEqual(model(row(i*5000)),[])  # target tail intersects reservation
        for i in range(7):self.assertEqual(model(row(300000+i*5000)),[])
        self.assertEqual(model(row(335000,symbol='XRPUSDT')),[])
        self.assertEqual(model(row(340000)),[])  # >7s gap resets SOL
        for i in range(1,7):self.assertEqual(model(row(340000+i*5000)),[])
        self.assertEqual(model(row(375000,session='b')),[])
        self.assertEqual(calls,[])

    def test_invalid_or_future_state_fails(self):
        model=SequenceSignals(lambda x:np.full((1,8),np.nan))
        for i in range(7):model(row(i*5000))
        with self.assertRaises(ValueError):model(row(35000))
        with self.assertRaises(ValueError):model(row(30000))
        with self.assertRaises(ValueError):SequenceSignals(lambda x:x,uncertainty=[-1]*8)

    def test_neural_units_scaling_and_eval(self):
        torch.manual_seed(7);net=ImpulseNet('mlp');mean=np.ones(30,dtype='float32');std=mean*2
        predict=neural_predictor(net,mean,std,device='cpu');x=np.full((1,8,30),3,dtype='float32')
        with torch.no_grad():expected=net(torch.ones(1,8,30)).numpy()/100
        np.testing.assert_equal(predict(x),expected);self.assertFalse(net.training)


if __name__=='__main__':unittest.main()
