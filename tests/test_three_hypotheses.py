import unittest
import tempfile,json
from pathlib import Path
import numpy as np
from research.execution import Account
from research.hypothesis_a import LeaderPolicy
from research.compare import choose,feasible,atomic_json,summarize
from research.hypothesis_c import groups

INST={s:dict(lotSizeFilter=dict(qtyStep='.1',minOrderQty='.1',minNotionalValue='5'))
      for s in ('SOLUSDT','DOGEUSDT','XRPUSDT','BNBUSDT','BTCUSDT')}
def quote(t,mid=100.,symbol='SOLUSDT'):
    return dict(ts=t,symbol=symbol,bids=[(mid-.01,100.)],asks=[(mid+.01,100.)])


class ResearchTests(unittest.TestCase):
    def test_cash_is_baseline_not_hypothesis_c(self):
        r=summarize({'base/CASH':{'net_pnl':0.},'base/C_rule':{'net_pnl':-.1}})
        self.assertEqual(r['C']['best_development_variant'],'base/C_rule')

    def test_numpy_scalars_are_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'result.json';atomic_json(p,{'lagging':np.bool_(True),'return':np.float64(-.1)})
            self.assertEqual(json.loads(p.read_text()),{'lagging':True,'return':-.1})

    def test_delayed_depth_and_cost_identity(self):
        for side in (1,-1):
            a=Account(INST);a.enter('SOLUSDT',side,10000)
            a.book(quote(10999,99.));self.assertIsNone(a.position)
            a.book(quote(11000,100.));self.assertEqual(a.position['opened_ms'],11000)
            a.act({'kind':'CLOSE'},12000);a.book(quote(12999,101.));self.assertIsNotNone(a.position)
            a.book(quote(13000,101.));r=a.result()
            self.assertEqual(r['trades'],1);self.assertAlmostEqual(r['trades_detail'][0]['cost_residual'],0.)
            self.assertAlmostEqual(r['net_pnl'],r['mid_gross_pnl']-r['spread']-r['depth_impact']-r['slippage']-r['fees'])

    def test_btc_minimum_is_not_fractionalized(self):
        inst=dict(INST);inst['BTCUSDT']=dict(lotSizeFilter=dict(qtyStep='.001',minOrderQty='.001',minNotionalValue='5'))
        a=Account(inst);q=quote(11000,84000.,'BTCUSDT')
        self.assertFalse(feasible(a,(1.,'BTCUSDT',1),{'BTCUSDT':q},11000))
        a.enter('BTCUSDT',1,10000);a.book(q)
        self.assertIsNone(a.position);self.assertEqual(a.rejections['quantity_or_depth'],1)

    def test_risk_halt_closes_and_never_raises_risk(self):
        a=Account(INST);a.enter('SOLUSDT',1,10000);a.book(quote(11000))
        a.book(quote(12000,80.));self.assertTrue(a.halted)
        a.book(quote(13000,80.));self.assertIsNone(a.position)
        a.enter('SOLUSDT',1,15000);self.assertIsNone(a.pending)

    def test_future_signal_not_delivered(self):
        s=dict(leader='BTCUSDT',leader_return=.002,side=1,signal_ms=2000)
        a=LeaderPolicy([s]);a.quote(quote(900));a.quote(quote(1900))
        self.assertEqual(a.events(1999,['SOLUSDT']),[])
        self.assertEqual(len(a.events(2000,['SOLUSDT'])),1)
        a.quote(quote(3000,101.));self.assertEqual(a.curves[0]['lag_seconds'],1)
        self.assertEqual(a.curves[0]['observation_delay_ms'],0)

    def test_future_scores_cannot_replace_current(self):
        x=np.zeros(30);latest={'SOLUSDT':(1000,x)}
        scores={'C':{(1000,'SOLUSDT'):(np.array([1.,0.]),np.array([1.,0.]))}}
        before=choose('C_boost',latest,scores,1000)
        scores['C'][(2000,'SOLUSDT')]=(np.array([-999.,999.]),np.array([-999.,999.]))
        self.assertEqual(before,choose('C_boost',latest,scores,1000))

    def test_training_label_uses_post_latency_quote(self):
        bt=np.arange(1000,151000,1000,dtype='int64');depth=np.tile(np.array([[[99.99,100]],[[100.01,100]]]),(len(bt),1,1,1))
        t=dict(bt=bt,bs=np.zeros(len(bt),dtype='int8'),depth=depth,
               ft=np.array([5000]),fs=np.array([0]),fx=np.zeros((1,30),dtype='float32'))
        a=groups(t,INST,'C');t['depth'][bt==5000]=np.array([[[1.,100]],[[2.,100]]])
        b=groups(t,INST,'C');np.testing.assert_array_equal(a[0][1],b[0][1])
        t['depth'][bt==6000]=np.array([[[109.99,100]],[[110.01,100]]])
        c=groups(t,INST,'C');self.assertFalse(np.array_equal(a[0][1],c[0][1]))


if __name__=='__main__':unittest.main()
