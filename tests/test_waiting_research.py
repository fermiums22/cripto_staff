import unittest
import waiting_research as research


class WaitingResearchTests(unittest.TestCase):
    def test_signal_is_causal_and_volume_filter_is_separate(self):
        bars=[[i*60000,100,101,99,100,10] for i in range(30)]
        bars[21][4]=99.9;bars[22][4]=100;bars[23][4]=100.1;bars[23][5]=30
        market={s:[r[:] for r in bars] for s in ('BTCUSDT','ETHUSDT','SOLUSDT')}
        before=research.signals(market)
        self.assertGreater(before['regime']['ETHUSDT'][23],0)
        market['ETHUSDT'][23][5]=10
        after=research.signals(market)
        self.assertEqual(after['volume']['ETHUSDT'][23],0)
        self.assertGreater(after['dip']['ETHUSDT'][23],0)
        market['ETHUSDT'][29][4]=500
        future=research.signals(market)
        self.assertEqual(after['dip']['ETHUSDT'][:29],future['dip']['ETHUSDT'][:29])
