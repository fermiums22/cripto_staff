import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent
import paper_arena as arena
import telegram_control as tg


class ArenaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(agent,'DATA',Path(self.tmp.name));self.patch.start()
        self.db=agent.connect();arena.setup(self.db);self.now=1800000000000
        self.quotes={s:dict(ts=self.now,bid=100.,ask=100.01,bid_size=100,ask_size=10) for s in agent.SYMBOLS}
        self.history={s:[] for s in agent.SYMBOLS}
        self.instruments={s:dict(status='Trading',lotSizeFilter={'basePrecision':'.001','minOrderQty':'.001','minOrderAmt':'5'}) for s in agent.SYMBOLS}

    def tearDown(self):
        self.db.close();self.patch.stop();self.tmp.cleanup()

    def state(self,key='pressure60'):
        return json.loads(self.db.execute('SELECT payload FROM arena_accounts WHERE id=?',(key,)).fetchone()[0])

    def step(self):
        arena.step(self.db,self.quotes,self.history,self.instruments,self.now)

    def test_entry_is_persisted_without_duplicate_after_setup(self):
        self.step();first=self.state()
        self.assertIsNotNone(first['position']);self.assertLess(first['equity'],15)
        arena.setup(self.db);self.step()
        self.assertEqual(self.db.execute("SELECT count(*) FROM events WHERE kind='paper_entry'").fetchone()[0],1)
        self.assertEqual(self.state()['cash'],first['cash'])

    def test_pause_keeps_timeout_exit_and_net_fees(self):
        self.step();tg.set_paused(self.db,True)
        self.now+=61000
        for q in self.quotes.values():q['ts']=self.now
        self.step();state=self.state()
        self.assertIsNone(state['position']);self.assertEqual(state['trades'],1)
        self.assertLess(state['cash'],15);self.assertGreater(state['fees'],0)
        event=json.loads(self.db.execute("SELECT payload FROM events WHERE kind='paper_exit'").fetchone()[0])
        self.assertEqual(event['reason'],'timeout');self.assertIn('strategy_name',event)

    def test_stale_quotes_cannot_open_or_fake_exit(self):
        self.now+=11000;self.step();self.assertIsNone(self.state()['position'])
        self.now-=11000;self.step();self.assertIsNotNone(self.state()['position'])
        self.now+=61000;self.step();self.assertIsNotNone(self.state()['position'])
        self.assertEqual(self.state()['reason'],'stale_quote')

    def test_wide_spread_and_loss_limit_block_entries(self):
        for q in self.quotes.values():q['ask']=101
        self.step();self.assertIsNone(self.state()['position'])
        for q in self.quotes.values():q['ask']=100.01
        state=self.state();state['cash']=12
        with self.db:self.db.execute('UPDATE arena_accounts SET payload=? WHERE id=?',(json.dumps(state),'pressure60'))
        self.step();self.assertIsNone(self.state()['position']);self.assertEqual(self.state()['reason'],'loss_limit')

    def test_v2_rejects_small_moves_and_history_gaps(self):
        self.history={s:[(self.now-180000+i*5000,100+i*.0001) for i in range(36)] for s in agent.SYMBOLS}
        for k in ('leadlag_cost_v2','breakout_cost_v2','rebound_cost_v2'):
            self.assertEqual(arena.signal(k,'ETHUSDT',self.history,self.quotes),0)
        self.quotes['ETHUSDT'].update(bid=101,ask=101.01)
        self.assertGreater(arena.signal('breakout_cost_v2','ETHUSDT',self.history,self.quotes),0)
        self.history['ETHUSDT']=self.history['ETHUSDT'][:10]+self.history['ETHUSDT'][15:]
        self.assertEqual(arena.signal('breakout_cost_v2','ETHUSDT',self.history,self.quotes),0)

    def test_v2_leadlag_uses_current_btc_and_preserves_accounts(self):
        self.history={s:[(self.now-180000+i*5000,100+i*.002) for i in range(36)] for s in agent.SYMBOLS}
        self.quotes['BTCUSDT'].update(bid=101,ask=101.01)
        self.quotes['ETHUSDT'].update(bid=100.2,ask=100.21)
        self.assertGreater(arena.signal('leadlag_cost_v2','ETHUSDT',self.history,self.quotes),0)
        self.quotes['BTCUSDT']['ts']-=20000
        self.assertEqual(arena.signal('leadlag_cost_v2','ETHUSDT',self.history,self.quotes),0)
        old=self.state();old['cash']=12.34
        with self.db:self.db.execute('UPDATE arena_accounts SET payload=? WHERE id=?',(json.dumps(old),'pressure60'))
        arena.setup(self.db)
        self.assertEqual(self.state()['cash'],12.34)
        self.assertEqual(self.state('leadlag_cost_v2')['cash'],15)
