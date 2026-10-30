import copy
import json
import unittest
from unittest.mock import patch
from adaptive_engine import Wallet, STEP, SCENARIOS, features, choose, rounded, order_qty, simulate
from adaptive_live import public, fresh_quote, closed_features


def instrument():
    return dict(priceFilter={'tickSize':'.01'},leverageFilter={'maxLeverage':'20'},
                lotSizeFilter={'qtyStep':'.001','minOrderQty':'.001','minNotionalValue':'5','maxMktOrderQty':'100'})


RISK = dict(maxLeverage='20',riskLimitValue='10000',maintenanceMargin='.005',mmDeduction='0')
CONFIG = dict(family='impulse',families=['impulse'],exit='trail',leverage=1,threshold=.003,stop=.02,hold_bars=32)
CANDIDATE = dict(symbol='SOLUSDT',side=1,family='impulse',reason='test',regime='up')


class AdaptiveTests(unittest.TestCase):
    def wallet(self,**config):
        w = Wallet(dict(CONFIG,**config))
        self.assertTrue(w.enter(CANDIDATE,100,100*STEP,instrument(),RISK))
        return w

    def test_rounding_and_minimum(self):
        self.assertEqual(order_qty(4,100,instrument()),0)
        self.assertEqual(order_qty(5.099,100,instrument()),.05)
        self.assertEqual(rounded(1.001,1,instrument()),1.01)
        self.assertEqual(rounded(1.009,-1,instrument()),1.)

    def test_shared_wallet_fee_and_funding_reconcile(self):
        w = self.wallet(); q = w.s['position']['qty']; entry = w.s['position']['entry']
        self.assertFalse(w.enter(dict(CANDIDATE,symbol='ETHUSDT'),100,100*STEP,instrument(),RISK))
        w.apply_funding(100,.001);w.close(103,101*STEP,'test')
        t = w.s['trades'][0]
        self.assertAlmostEqual(t['fees'],q*(entry+t['exit'])*.001)
        self.assertAlmostEqual(t['net'],t['gross']-t['fees']+t['funding'])
        self.assertAlmostEqual(w.s['cash'],15+t['net'])

    def test_gap_stop_uses_worse_open(self):
        w = self.wallet();w.update([101*STEP,90,91,89,90,1],[101*STEP,90,91,89,90])
        t = w.s['trades'][0];self.assertEqual(t['exit_reason'],'stop');self.assertLess(t['exit'],90)

    def test_stop_beats_take_on_ambiguous_bar(self):
        w = self.wallet(exit='early')
        w.update([101*STEP,100,103,97,100,1],[101*STEP,100,103,97,100])
        self.assertEqual(w.s['trades'][0]['exit_reason'],'stop')

    def test_trail_activated_only_next_bar(self):
        w = self.wallet()
        w.update([101*STEP,100,104,99,103,1],[101*STEP,100,104,99,103])
        self.assertIsNotNone(w.s['position'])
        w.update([102*STEP,103,103,101,102,1],[102*STEP,103,103,101,102])
        self.assertEqual(w.s['trades'][0]['exit_reason'],'stop')

    def test_liquidation_and_extreme_short_gap(self):
        w = Wallet(dict(CONFIG,leverage=10))
        self.assertTrue(w.enter(dict(CANDIDATE,side=-1),100,100*STEP,instrument(),RISK))
        reserved = w.s['cash']
        w.update([101*STEP,1000,1000,1000,1000,1],[101*STEP,1000,1000,1000,1000])
        self.assertEqual(w.s['liquidations'],1);self.assertGreaterEqual(w.s['cash'],reserved)
        self.assertAlmostEqual(w.s['cash'],15+sum(t['net'] for t in w.s['trades']))

    def test_winning_pyramid_only_and_reconciliation(self):
        w = self.wallet(leverage=3)
        self.assertFalse(w.enter(CANDIDATE,99,101*STEP,instrument(),RISK,add=True))
        self.assertTrue(w.enter(CANDIDATE,103,101*STEP,instrument(),RISK,add=True))
        self.assertFalse(w.enter(CANDIDATE,104,102*STEP,instrument(),RISK,add=True))
        w.apply_funding(103,-.001);w.close(104,103*STEP,'test')
        self.assertAlmostEqual(w.s['cash'],15+w.s['trades'][0]['net'])

    def test_persistence_keeps_balance_and_position(self):
        w = self.wallet();w.apply_funding(100,.001)
        restored = Wallet(CONFIG,state=json.loads(json.dumps(w.s)))
        restored.close(102,102*STEP,'test');w.close(102,102*STEP,'test')
        self.assertEqual(restored.s,w.s)

    def test_features_have_no_future_and_reject_gaps(self):
        bars = [[i*STEP,100+i,101+i,99+i,100+i,10] for i in range(70)]
        before = features(bars,40);bars[41][4]=999999
        self.assertEqual(before,features(bars,40))
        bars[39][0]+=1;self.assertIsNone(features(bars,40))

    def test_simulation_uses_previous_closed_signal(self):
        bars = [[i*STEP,100,101,99,100,10] for i in range(70)]
        m = dict(SOLUSDT=dict(trade=bars,mark=[b[:5] for b in bars],funding=[],instrument=instrument(),risk=RISK))
        f = {s:[None]*70 for s in m}
        with patch('adaptive_engine.choose',return_value=None) as choose_mock:
            simulate(m,f,CONFIG,33,40)
            self.assertEqual(choose_mock.call_count,7)
        f['SOLUSDT'][40]={'sentinel':'future'}
        def check(observations,*args):
            self.assertNotIn({'sentinel':'future'},observations.values());return None
        with patch('adaptive_engine.choose',side_effect=check):
            self.assertEqual(simulate(m,f,CONFIG,33,40)['capital'],15)

    def test_cost_gate_and_unsafe_leverage(self):
        f = dict(m1=.003,m3=.004,m8=.004,m32=.01,volume=2.,volatility=.001,ts=STEP,wick=0.)
        self.assertIsNone(choose({'SOLUSDT':f},CONFIG,SCENARIOS['realistic']))
        w = Wallet(dict(CONFIG,leverage=100))
        self.assertFalse(w.enter(CANDIDATE,100,STEP,instrument(),RISK))

    def test_public_only_no_order_api(self):
        with patch('agent.api') as api:
            for endpoint in ('order/create','../order/create','wallet-balance','position/list'):
                with self.assertRaises(ValueError):public(endpoint)
            api.assert_not_called()

    def test_stale_and_crossed_quotes(self):
        r = dict(time=100000,result={'list':[dict(symbol='SOLUSDT',bid1Price='2',ask1Price='1',markPrice='1.5')]})
        self.assertEqual(fresh_quote(r,100000)[1],{})
        with self.assertRaises(ValueError):fresh_quote(r,200000)

    def test_live_excludes_open_candle(self):
        bars = [[i*STEP,100,101,99,100,10] for i in range(66)]
        bars[-1][4]=9000
        with patch('adaptive_live.public',return_value={'result':{'list':bars}}):
            _,f = closed_features('SOLUSDT',65*STEP+10)
        self.assertEqual(f['price'],100);self.assertEqual(f['ts'],65*STEP)


if __name__=='__main__':unittest.main()
