import unittest
import arena_backtest as bt


class BacktestTests(unittest.TestCase):
    def test_ambiguous_bar_is_stop_first_and_gap_uses_open(self):
        self.assertEqual(bt.exit_hit([0,100,102,98,100,1],100,0),(99.8,'stop'))
        self.assertEqual(bt.exit_hit([0,98,102,97,100,1],100,0),(98,'stop'))

    def test_signal_executes_next_open_not_signal_close(self):
        bars=[[0,100,100,100,100,1],[60000,110,110,110,110,1],[120000,110,110,110,110,1]]
        lots={'BTCUSDT':dict(basePrecision='.001',minOrderQty='.001',minOrderAmt='5')}
        r=bt.simulate({'BTCUSDT':bars},{'BTCUSDT':[1,0,0]},lots,0)
        self.assertEqual(r['trades'],1)
        self.assertLess(r['return_pct'],0)
        self.assertGreater(r['return_pct'],-1)
        r=bt.simulate({'BTCUSDT':bars},{'BTCUSDT':[0,0,1]},lots,0)
        self.assertEqual(r['trades'],0)
        self.assertEqual(r['equity'],15)
