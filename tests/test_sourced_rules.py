import unittest
from sourced_rules import entry_scores,aggregate


class SourceRulesTests(unittest.TestCase):
    def test_no_future_or_flat_signals(self):
        prices=[100.]*220
        self.assertFalse(any(entry_scores(prices)['hb_bollinger']))
        prices[-1]=90
        scores=entry_scores(prices)
        self.assertGreater(scores['hb_bollinger'][-1],0)
        self.assertEqual(scores['hb_bollinger'][:-1],entry_scores(prices[:-1])['hb_bollinger'])

    def test_no_partial_three_minute_candle(self):
        rows=[[i*60000,100,102,99,101,2] for i in range(5)]
        out=aggregate(rows)
        self.assertEqual(len(out),1)
        self.assertEqual(out[0],[0,100,102,99,101,6])
