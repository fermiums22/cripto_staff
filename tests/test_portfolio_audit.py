import importlib.util
import unittest
import numpy as np
from test_portfolio import market
from portfolio_sim import simulate

HAS_TORCH=importlib.util.find_spec('torch') is not None
if HAS_TORCH:
    from portfolio_audit import reprice,summarize


@unittest.skipUnless(HAS_TORCH,'Optional research dependencies required')
class AuditTests(unittest.TestCase):
    def test_reprice_reconciles_and_stress_increases_cost(self):
        m=market();p={s:np.full(260,.02) for s in m}
        r=simulate(m,p,100,160)
        base=reprice(r['records'],m,.0006,.001)
        stress=reprice(r['records'],m,.0016,.001)
        self.assertAlmostEqual(base['capital'],r['capital'])
        self.assertGreater(stress['friction_cost'],base['friction_cost'])
        self.assertAlmostEqual(base['reference_gross'],stress['reference_gross'])

    def test_coin_totals_reconcile(self):
        m=market();p={s:np.full(260,.02) for s in m}
        r=simulate(m,p,100,160);s=summarize(r['records'])
        self.assertAlmostEqual(sum(v['net'] for v in s.values()),r['capital']-15)
        self.assertEqual(sum(v['trades'] for v in s.values()),r['trades'])


if __name__=='__main__':unittest.main()
