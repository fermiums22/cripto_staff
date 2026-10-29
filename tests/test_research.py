import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent
import telegram_control as tg
import research_worker as worker


class ResearchTests(unittest.TestCase):
    def test_final_period_boundary_cannot_be_read(self):
        bars=[[i*60000,100,100,100,100,1] for i in range(10)]
        bars[5]=[300000,200,300,200,250,1]
        closed,price,entry=worker.outcome(bars,3,(.5,.5,10),0,end=5)
        self.assertEqual((closed,price),(4,100))

    def test_stop_precedes_take_within_minute(self):
        bars=[[0,100,110,90,105,1]]
        self.assertEqual(worker.outcome(bars,0,(.01,.01,3),0)[1],99)

    def test_future_bar_not_used_before_entry(self):
        bars=[[i*60000,100,100,100,100,1] for i in range(10)]
        scores=[0]*10;scores[-1]=1
        lot={'basePrecision':'.001','minOrderQty':'.001','minOrderAmt':'5'}
        r=worker.simulate(bars,scores,0,10,(.01,.01,3),.5,lot)
        self.assertEqual(r['trades'],0)

    def test_notification_preferences_and_no_duplicate_or_history(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(agent,'DATA',Path(tmp)):
            db=agent.connect();tg.notification_schema(db)
            payload=json.dumps({'symbol':'BTCUSDT','entry':100,'qty':.1,'cost':10.01})
            with db:db.execute("INSERT INTO events(ts,kind,payload) VALUES (0,'paper_entry',?)",(payload,))
            tg.subscribe(db,123,True)
            with db:db.execute("INSERT INTO events(ts,kind,payload) VALUES (1,'paper_entry',?)",(payload,))
            with patch.object(tg,'call') as send:
                tg.deliver_notifications(db,'test',{'user_ids':[]});send.assert_not_called()
                tg.deliver_notifications(db,'test',{'user_ids':[123]})
                tg.deliver_notifications(db,'test',{'user_ids':[123]})
                self.assertEqual(send.call_count,1)
                self.assertIn('ВИРТУАЛЬНЫЙ',send.call_args.args[2]['text'])
                tg.subscribe(db,123,False)
                with db:db.execute("INSERT INTO events(ts,kind,payload) VALUES (2,'paper_entry',?)",(payload,))
                tg.deliver_notifications(db,'test',{'user_ids':[123]})
                self.assertEqual(send.call_count,1)
            db.close()

    def test_failed_notification_not_retried_as_fake_new_trade(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(agent,'DATA',Path(tmp)):
            db=agent.connect();tg.notification_schema(db);tg.subscribe(db,123,True)
            payload=json.dumps({'symbol':'BTCUSDT','entry':100,'qty':.1,'cost':10.01})
            with db:db.execute("INSERT INTO events(ts,kind,payload) VALUES (1,'paper_entry',?)",(payload,))
            with patch.object(tg,'call',side_effect=RuntimeError('network')) as send:
                tg.deliver_notifications(db,'test',{'user_ids':[123]})
                tg.deliver_notifications(db,'test',{'user_ids':[123]})
                self.assertEqual(send.call_count,1)
                self.assertEqual(db.execute('SELECT status FROM deliveries').fetchone()[0],'unknown')
            db.close()
