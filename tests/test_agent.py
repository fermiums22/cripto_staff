import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent


class AgentTests(unittest.TestCase):
    def test_only_closed_candles(self):
        rows = [[0, 100, 101, 99, 100, 10], [300000, 100, 101, 99, 100, 10]]
        self.assertEqual(len(agent.closed_bars(rows, 599999)), 1)
        self.assertEqual(len(agent.closed_bars(rows, 600000)), 2)

    def test_invalid_candle_rejected(self):
        with self.assertRaises(ValueError):
            agent.closed_bars([[0, 100, 90, 99, 100, 10]], 300000)

    def test_features_do_not_read_future(self):
        bars = [[i*agent.BAR_MS, 100, 101, 99, 100+i/100, 10] for i in range(40)]
        before = agent.features(bars, 24)
        bars[25][4] = 999999
        self.assertEqual(before, agent.features(bars, 24))

    def test_gap_blocks_signal(self):
        bars = [[i*agent.BAR_MS, 100, 101, 99, 100, 10] for i in range(30)]
        bars[20][0] += 1
        self.assertIsNone(agent.features(bars, 29))

    def test_both_stops_in_bar_use_adverse_order(self):
        price, reason = agent.exit_price([0, 100, 110, 90, 105, 10], 100, 1)
        self.assertEqual(reason, 'stop')
        self.assertEqual(price, 99)

    def test_gap_stop_uses_worse_open(self):
        price, reason = agent.exit_price([0, 90, 100, 85, 95, 10], 100, 1)
        self.assertEqual((price, reason), (90, 'gap_stop'))

    def test_signal_executes_only_next_bar_and_pays_costs(self):
        bars = [[i*agent.BAR_MS, 100, 100, 100, 100, 10] for i in range(4)]
        result = agent.backtest(bars, {3: 1}, 0, 4)
        self.assertEqual(result['trades'], 0)
        result = agent.backtest(bars, {0: 1}, 0, 4)
        self.assertEqual(result['trades'], 1)
        self.assertLess(result['end_usdt'], 15)

    def test_minimum_order_and_rounding(self):
        lot = {'basePrecision': '0.001', 'minOrderQty': '0.001', 'minOrderAmt': '5'}
        self.assertEqual(agent.order_quantity(1, 100, lot), 0)
        qty = agent.order_quantity(15, 100, lot)
        self.assertAlmostEqual(qty, 0.134)
        self.assertLessEqual(qty*100*(1+agent.SLIP)*(1+agent.FEE), 13.5)

    def test_cycle_is_durable_and_idempotent(self):
        now = 1800000001000
        latest = (now // agent.BAR_MS - 1)*agent.BAR_MS
        bars = [[latest-(29-i)*agent.BAR_MS, 100, 101, 99, 100, 10] for i in range(30)]
        quote = {'time': now, 'result': {'list': [{'bid1Price': '100', 'ask1Price': '100.01'}]}}
        models = {s: {'id': 'test-only'} for s in agent.SYMBOLS}
        instruments = {s: {'lotSizeFilter': {'basePrecision': '0.001', 'minOrderQty': '0.001',
                                            'minOrderAmt': '5'}} for s in agent.SYMBOLS}
        with tempfile.TemporaryDirectory() as tmp, patch.object(agent, 'DATA', Path(tmp)), \
                patch.object(agent, 'collect'), patch.object(agent, 'read_bars', return_value=bars), \
                patch.object(agent, 'api', return_value=quote), \
                patch.object(agent, 'probability', return_value=0.8), \
                patch.object(agent.time, 'time', return_value=now/1000):
            db = agent.connect()
            agent.cycle(db, models, instruments)
            first = db.execute("SELECT value FROM state WHERE key='portfolio'").fetchone()[0]
            db.close()
            db = agent.connect()
            agent.cycle(db, models, instruments)
            second = db.execute("SELECT value FROM state WHERE key='portfolio'").fetchone()[0]
            self.assertEqual(first, second)
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='paper_entry'").fetchone()[0], 1)
            self.assertGreaterEqual(json.loads(second)['cash'], 0)
            db.close()


if __name__ == '__main__':
    unittest.main()
