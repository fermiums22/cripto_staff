import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import agent
import dashboard
import telegram_control as tg
import strategy_lab


class ControlTests(unittest.TestCase):
    def message(self, uid=123, text='/pause', kind='private'):
        return {'from': {'id': uid, 'is_bot': False}, 'chat': {'id': uid, 'type': kind}, 'text': text}

    def test_allowlist_required_for_every_control(self):
        for text in ['/pause', '/resume', '/status', '/chart', '/start', 'Статус', 'График']:
            self.assertEqual(tg.action_for(self.message(text=text), {'user_ids': []}), 'deny')
        self.assertEqual(tg.action_for(self.message(text='/id'), {'user_ids': []}), 'id')
        self.assertEqual(tg.action_for(self.message(), {'user_ids': [123]}), 'pause')

    def test_group_and_impersonated_chat_rejected(self):
        self.assertEqual(tg.action_for(self.message(kind='group', text='/id'), {'user_ids': [123]}), 'deny')
        m = self.message(); m['chat']['id'] = 999
        self.assertFalse(tg.authorized(m, {'user_ids': [123]}))

    def test_pause_persists_across_connection(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(agent, 'DATA', Path(tmp)):
            db = agent.connect(); tg.set_paused(db, True); db.close()
            db = agent.connect()
            self.assertTrue(json.loads(db.execute("SELECT value FROM state WHERE key='control'").fetchone()[0])['paused'])
            db.close()

    def test_future_cross_asset_prices_not_used(self):
        market = {s: [[i*agent.BAR_MS, 100, 101, 99, 100, 10] for i in range(35)] for s in agent.SYMBOLS}
        x = strategy_lab.cross_features(market, 'SOLUSDT', 25)
        market['BTCUSDT'][26][4] = 999999
        self.assertEqual(x, strategy_lab.cross_features(market, 'SOLUSDT', 25))

    def test_web_server_never_serves_secrets(self):
        server = dashboard.ThreadingHTTPServer(('127.0.0.1', 0), dashboard.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            for path in ['/secrets/bybit.key', '/crypto_cey', '/.git/config', '/../agent.py']:
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+path)
                self.assertEqual(caught.exception.code, 404)
                caught.exception.close()
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_pause_blocks_entries_but_keeps_exits(self):
        now = 1800000001000
        latest = (now//agent.BAR_MS-1)*agent.BAR_MS
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
            db = agent.connect(); tg.set_paused(db, True)
            agent.cycle(db, models, instruments)
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 0)
            position = {'symbol': 'BTCUSDT', 'qty': 0.1, 'entry': 110, 'cost': 11.011, 'opened_ms': now-1000}
            with db:
                db.execute("UPDATE state SET value=? WHERE key='portfolio'",
                           (json.dumps({'cash': 3.989, 'position': position}),))
            agent.cycle(db, models, instruments)
            portfolio = json.loads(db.execute("SELECT value FROM state WHERE key='portfolio'").fetchone()[0])
            self.assertIsNone(portfolio['position'])
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='paper_exit'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE kind='paper_entry'").fetchone()[0], 0)
            db.close()
