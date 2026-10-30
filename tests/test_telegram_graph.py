import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import agent
import dashboard


@unittest.skipUnless(importlib.util.find_spec('matplotlib'), 'Matplotlib required')
class TelegramGraphTests(unittest.TestCase):
    def render(self, data):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        original = plt.subplots
        captured = []
        def subplots(*args, **kwargs):
            result = original(*args, **kwargs); captured.append(result); return result
        with tempfile.TemporaryDirectory() as temp, patch.object(agent, 'ARTIFACTS', Path(temp)), \
                patch.object(dashboard, 'snapshot', side_effect=AssertionError('Legacy arena must not be read')), \
                patch.object(dashboard.time, 'time', return_value=1000), \
                patch.object(plt, 'subplots', side_effect=subplots):
            if data is not None:
                (Path(temp)/'adaptive_live.json').write_text(json.dumps(data), encoding='utf-8')
            png = dashboard.graph_png()
        self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))
        return captured[0]

    def test_current_adaptive_wallet_and_collection_gate(self):
        fig, ax = self.render(dict(selected='leadlag_trail_0.003', updated_ms=999000, equity=15., live_gate=False,
            wallet=dict(curve=[[900000,15.],[999000,15.]], position=None, trades=[])))
        self.assertEqual(len(fig.axes), 1)
        self.assertEqual(list(ax.lines[0].get_ydata()), [15.,15.])
        self.assertIn('LIVE PAPER', ax.lines[0].get_label())
        labels = '\n'.join(t.get_text() for t in fig.texts)
        self.assertIn('leadlag_trail_0.003', labels)
        self.assertIn('входы отключены', labels)
        self.assertIn('1 с назад', labels)
        self.assertNotIn('BTCUSDT', labels)

    def test_failed_cycle_marks_stale_wallet(self):
        fig, _ = self.render(dict(selected='test', updated_ms=999000, last_error='TimeoutError',
            wallet=dict(curve=[[900000,14.]], position=None, trades=[])))
        labels = '\n'.join(t.get_text() for t in fig.texts)
        self.assertIn('ВНИМАНИЕ', labels)
        self.assertIn('$14.0000', labels)

    def test_no_artifact_does_not_fabricate_wallet_history(self):
        fig, ax = self.render(None)
        self.assertEqual(len(ax.lines), 1)  # Only the explicitly labeled $15 baseline.
        labels = '\n'.join(t.get_text() for t in fig.texts)
        self.assertIn('Капитал нет данных', labels)
        self.assertIn('Ожидание данных', labels)
