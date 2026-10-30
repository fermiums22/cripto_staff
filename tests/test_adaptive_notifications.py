import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import agent
import telegram_control as tg
from adaptive_live import event_schema, persist_cycle

ENTRY = dict(symbol='SOLUSDT',side=1,entry=100.,qty=.1,margin=10.,fees=.01,
             reason='signal',opened_ms=1000)
TRADE = dict(symbol='SOLUSDT',side=1,exit_reason='stop',net=-.2,fees=.02,
             funding=0.,balance=14.8,closed_ms=2000)


def saved(position=None, trades=None):
    return dict(wallet=dict(position=copy.deepcopy(position),trades=copy.deepcopy(trades or [])))


def source(path):
    db=sqlite3.connect(path)
    db.execute('CREATE TABLE state (id INTEGER PRIMARY KEY, payload TEXT)')
    event_schema(db)
    return db


class AdaptiveNotificationTests(unittest.TestCase):
    def test_status_uses_adaptive_wallet_only(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(agent,'ARTIFACTS',Path(temp)), \
                patch.object(tg.dashboard,'snapshot',side_effect=AssertionError('Legacy source')), \
                patch.object(agent,'api',side_effect=AssertionError('No API required')):
            data=dict(selected='adaptive-test',updated_ms=999000,live_gate=False,equity=15.,
                      wallet=dict(position=None,trades=[],curve=[[999000,15.]]),metrics={'trades':1})
            (Path(temp)/'adaptive_live.json').write_text(json.dumps(data),encoding='utf-8')
            with patch.object(tg.time,'time',return_value=1000):text=tg.status_text()
            self.assertIn('Закрыто сделок: 0',text)
            self.assertIn('входы заблокированы',text)
            self.assertIn('1 с назад',text)
            self.assertNotIn('Bollinger',text)
            data['last_error']='TimeoutError'
            (Path(temp)/'adaptive_live.json').write_text(json.dumps(data),encoding='utf-8')
            self.assertIn('ВНИМАНИЕ',tg.status_text())

    def test_outbox_bridging_filtering_and_no_duplicates(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(agent,'DATA',Path(temp)):
            db=agent.connect();tg.notification_schema(db);tg.subscribe(db,123,True)
            outbox=source(Path(temp)/'adaptive.sqlite3');before=saved();opened=saved(ENTRY)
            persist_cycle(outbox,before,opened,'adaptive-test')
            persist_cycle(outbox,opened,opened,'adaptive-test')
            self.assertEqual(outbox.execute('SELECT count(*) FROM events').fetchone()[0],1)
            with db:db.execute("INSERT INTO events(ts,kind,payload) VALUES (0,'paper_entry',?)",(json.dumps(dict(strategy='hb_bollinger')),))
            tg.bridge_adaptive_events(db);tg.bridge_adaptive_events(db)
            with patch.object(tg,'call') as send:
                tg.deliver_notifications(db,'test',{'user_ids':[123]},strategy='adaptive')
                tg.deliver_notifications(db,'test',{'user_ids':[123]},strategy='adaptive')
                self.assertEqual(send.call_count,1)
                self.assertIn('ВИРТУАЛЬНЫЙ ВХОД',send.call_args.args[2]['text'])
                closed=saved(trades=[TRADE]);persist_cycle(outbox,opened,closed,'adaptive-test')
                tg.bridge_adaptive_events(db)
                tg.deliver_notifications(db,'test',{'user_ids':[123]},strategy='adaptive')
                self.assertEqual(send.call_count,2)
                self.assertIn('ВИРТУАЛЬНЫЙ ВЫХОД',send.call_args.args[2]['text'])
                self.assertIn('-0.2000',send.call_args.args[2]['text'])
            outbox.close();db.close()

    def test_wallet_and_outbox_rollback_together(self):
        with tempfile.TemporaryDirectory() as temp:
            db=source(Path(temp)/'adaptive.sqlite3')
            db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'test'); END")
            with self.assertRaises(sqlite3.IntegrityError):persist_cycle(db,saved(),saved(ENTRY),'test')
            self.assertEqual(db.execute('SELECT count(*) FROM state').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],0)
            db.close()

    def test_enable_does_not_replay_existing_adaptive_events(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(agent,'DATA',Path(temp)):
            db=agent.connect();tg.notification_schema(db)
            outbox=source(Path(temp)/'adaptive.sqlite3')
            persist_cycle(outbox,saved(),saved(ENTRY),'test');tg.bridge_adaptive_events(db)
            tg.subscribe(db,123,True)
            with patch.object(tg,'call') as send:
                tg.deliver_notifications(db,'test',{'user_ids':[123]},strategy='adaptive')
                send.assert_not_called()
            outbox.close();db.close()
