import copy
import unittest
import numpy as np
from portfolio_sim import simulate,quantity,fill


def market():
    result={}
    for j,s in enumerate(['SOLUSDT','ALTUSDT','OTHERUSDT']):
        bars=[]
        for i in range(260):
            price=100+np.sin(i*(j+1))*.02
            bars.append([i*900000,price,price+.01,price-.01,price,10000.,100000.])
        result[s]=dict(trade=bars,mark=[b[:5] for b in bars],funding=[],
            instrument=dict(priceFilter={'tickSize':'.001'},leverageFilter={'maxLeverage':'10'},
                lotSizeFilter={'qtyStep':'.001','minOrderQty':'.001','minNotionalValue':'5','maxMktOrderQty':'100'}),
            risk={'riskLimitValue':'10000','maintenanceMargin':'.005','mmDeduction':'0','maxLeverage':'10'})
    return result


class PortfolioTests(unittest.TestCase):
    def test_minimum_and_step(self):
        lot=market()['SOLUSDT']['instrument']['lotSizeFilter']
        self.assertEqual(quantity(4,100,1,.001,lot),0)
        q=quantity(15,100,3,.001,lot)
        self.assertLessEqual(q*100*(1/3+.001),15)
        self.assertAlmostEqual(q/.001,round(q/.001))

    def test_shared_wallet_and_reconciliation(self):
        m=market();p={s:np.full(260,.02) for s in m}
        r=simulate(m,p,100,200,mode='multi')
        self.assertLessEqual(r['maximum_positions'],2)  # $15 cannot fund three $5 minima plus fees.
        self.assertAlmostEqual(r['capital'],15+sum(t['net'] for t in r['records']))
        for a in r['allocations']:
            self.assertGreaterEqual(a['cash'],-1e-8)
            self.assertLessEqual(sum(p['margin'] for p in a['positions']),15)

    def test_cash_and_no_future_signal(self):
        m=market();p={s:np.zeros(260) for s in m}
        r=simulate(m,p,100,150);self.assertEqual(r['capital'],15)
        p['SOLUSDT'][150:]=1
        self.assertEqual(simulate(m,p,100,150)['records'],[])

    def test_correlated_exposure_blocked(self):
        m=market();m['ALTUSDT']=copy.deepcopy(m['SOLUSDT']);m.pop('OTHERUSDT')
        r=simulate(m,{s:np.full(260,.02) for s in m},100,150)
        self.assertEqual(r['maximum_positions'],1);self.assertGreater(r['rejected']['correlated'],0)

    def test_isolated_liquidation_cannot_spend_other_cash(self):
        m=market();p={s:np.zeros(260) for s in m};p['SOLUSDT'][:]=-.02
        m['SOLUSDT']['mark'][105][2]=200
        r=simulate(m,p,100,110,mode='single',leverage=10)
        self.assertGreater(r['liquidations'],0);self.assertGreaterEqual(r['capital'],0)
        self.assertAlmostEqual(r['capital'],15+sum(t['net'] for t in r['records']))

    def test_funding_accounted_once(self):
        m=market();p={s:np.zeros(260) for s in m};p['SOLUSDT'][:]=.02
        m['SOLUSDT']['funding']=[dict(fundingRateTimestamp=str(105*900000),fundingRate='.01')]
        r=simulate(m,p,100,110,mode='single')
        self.assertLess(r['funding'],0)
        self.assertAlmostEqual(r['capital'],15+sum(t['net'] for t in r['records']))
        t=r['records'][0]
        self.assertAlmostEqual(t['net'],t['gross']-t['fees']+t['funding']+t['bankruptcy_adjustment'])

    def test_adverse_tick_rounding(self):
        ins=market()['SOLUSDT']['instrument']
        self.assertGreaterEqual(fill(100.0001,1,.0006,ins),100.0001*1.0006)
        self.assertLessEqual(fill(100.0001,-1,.0006,ins),100.0001*.9994)


if __name__=='__main__':unittest.main()
