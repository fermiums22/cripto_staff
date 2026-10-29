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
        finally:
            server.shutdown(); server.server_close(); thread.join()
