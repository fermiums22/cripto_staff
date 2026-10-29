import unittest
from execution_research import features,outcome,backtest


def data():
    bars=[[i*60000,100,100.01,99.99,100,1] for i in range(120)]
    return dict(trade=bars,mark=[r[:5] for r in bars],_rates={},instrument=dict(lotSizeFilter=dict(qtyStep='.01',minOrderQty='.01',minNotionalValue='5')))


class ExecutionResearchTests(unittest.TestCase):
    def test_post_only_can_expire_and_reject_crossing(self):
        d=data()
        self.assertIsNone(outcome(d,30,.01,.006,'maker',.00036,.001))
        d['trade'][31][1]=99
        self.assertIsNone(outcome(d,30,.01,.006,'maker',.00036,.001))

    def test_cash_reconciles_gross_fees_funding_and_features_causal(self):
        d=data();x=features(d['trade'],30);d['trade'][100][4]=999
        self.assertEqual(x,features(d['trade'],30))
        r,rows=backtest(d,{30:1},30,90,.01,.006,'taker',.5,False,.00036,.001)
        self.assertEqual(r['trades'],1)
        self.assertAlmostEqual(r['net_pnl'],r['gross_pnl']-r['fees']+r['funding'])
        self.assertLess(r['net_pnl'],0)
        self.assertEqual(rows[0]['reason'],'end')
