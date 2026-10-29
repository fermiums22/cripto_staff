import unittest
import importlib.util
import numpy as np
if importlib.util.find_spec('gymnasium'):
    from evolution_env import TradingEnv,market_features
else:
    TradingEnv=None


def fixture():
    bars=[[i*60000,100.,100.,100.,100.,10.] for i in range(150)]
    return dict(trade=bars,mark=[b[:5] for b in bars],funding=[],
        risk={'maintenanceMargin':'.005'},
        instrument={'lotSizeFilter':{'qtyStep':'.001','minOrderQty':'.001','minNotionalValue':'1'}})


@unittest.skipIf(TradingEnv is None,'Install requirements-evolution.txt for research environment tests')
class EnvironmentTests(unittest.TestCase):
    def make(self,data=None,**kw):
        data=data or fixture();x=market_features(data)
        return TradingEnv(data,x,np.zeros(9),np.ones(9),30,40,**kw)

    def test_flat_roundtrip_costs_and_reward_reconcile(self):
        e=self.make();total=0
        for action in [1,3]+[0]*7:
            _,r,done,_,_=e.step(action);total+=r
        self.assertTrue(done);self.assertLess(e.cash,15)
        self.assertAlmostEqual(e.cash,15+e.gross-e.fees+e.funding)
        self.assertAlmostEqual(e.cash,15+sum(t['net'] for t in e.trades))
        self.assertAlmostEqual(total,(e.cash-15)/15*100)

    def test_entry_uses_next_open_not_observed_close(self):
        d=fixture();d['trade'][31][1]=101
        e=self.make(d);e.step(1)
        self.assertAlmostEqual(e.entry,101*1.0006)

    def test_cash_baseline_and_terminal_close(self):
        e=self.make()
        for _ in range(9):e.step(0)
        self.assertEqual(e.cash,15);self.assertEqual(e.trades,[])
        e.reset()
        for _ in range(9):e.step(1)
        self.assertEqual(e.side,0);self.assertEqual(len(e.trades),1)
        with self.assertRaises(RuntimeError):e.step(0)

    def test_funding_existing_positions_only(self):
        d=fixture();d['funding']=[dict(fundingRateTimestamp=str(i*60000),fundingRate='.001') for i in (31,32)]
        e=self.make(d);e.step(1);qty=e.qty
        self.assertEqual(e.funding,0)
        e.step(3);self.assertAlmostEqual(e.funding,-qty*100*.001)
        self.assertAlmostEqual(e.cash,15+sum(t['net'] for t in e.trades))

    def test_gap_rejected_and_future_cannot_change_observation(self):
        d=fixture();e=self.make(d);before=e._obs().copy()
        d['trade'][35][4]=200
        np.testing.assert_array_equal(before,self.make(d)._obs())
        d['mark'][35][0]+=1
        with self.assertRaises(ValueError):market_features(d)

    def test_mark_liquidation_halts_without_topup(self):
        d=fixture();d['mark'][31][2]=1000
        e=self.make(d);_,_,done,_,_=e.step(2)
        self.assertTrue(done);self.assertEqual(e.liquidations,1);self.assertLess(e.cash,0)
        self.assertEqual(e.side,0)

    def test_gap_liquidates_before_discretionary_close(self):
        d=fixture();d['mark'][32][1]=1000
        e=self.make(d);e.step(2);_,_,done,_,_=e.step(3)
        self.assertTrue(done)
        self.assertEqual(e.trades[0]['reason'],'gap_liquidation_proxy')
        self.assertLess(e.cash,0)


if __name__=='__main__':unittest.main()
