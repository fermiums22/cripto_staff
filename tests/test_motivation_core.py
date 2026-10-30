import unittest
from motivation_core import Opportunity, Motives, assess

class MotivationCoreTests(unittest.TestCase):
    def sample(self,**kwargs):
        d=dict(symbol='BTCUSDT',observed_ms=100000,now_ms=100100,expected_move=.01,
               confidence=.9,roundtrip_fee=.001,spread=.0002,slippage=.0003,
               funding=0,liquidation_risk=.0001,depth_usd=10000,required_notional_usd=100)
        d.update(kwargs)
        return Opportunity(**d)
    def test_clean_entry(self):self.assertTrue(assess(self.sample()).eligible)
    def test_stale(self):self.assertEqual(assess(self.sample(now_ms=103000)).reason,'stale_or_future_signal')
    def test_expensive(self):self.assertFalse(assess(self.sample(roundtrip_fee=.012)).eligible)
    def test_liquidity(self):self.assertFalse(assess(self.sample(depth_usd=200)).eligible)
    def test_liquidation(self):self.assertFalse(assess(self.sample(liquidation_risk=.1)).eligible)
    def test_impatience_cannot_override(self):
        d=self.sample(expected_move=.0001)
        self.assertFalse(assess(d,Motives(impatience=1)).eligible)
    def test_no_lookahead(self):self.assertFalse(assess(self.sample(observed_ms=100200)).eligible)
if __name__=='__main__':unittest.main()
