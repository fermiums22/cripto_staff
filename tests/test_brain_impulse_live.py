import json
import sqlite3
import tempfile
from pathlib import Path
import unittest
from brain_impulse_audit import audit
from brain_impulse_live import paused
from brain_impulse_controls import signals
from brain_impulse_execution import DurablePaper
from brain_impulse_data import FEATURES
from test_brain_impulse_execution import book,signal,INST


class LiveTests(unittest.TestCase):
    def test_pause_is_readonly_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'control.db'
            self.assertTrue(paused(path));self.assertFalse(path.exists())
            db=sqlite3.connect(path);db.execute('CREATE TABLE state(key TEXT,value TEXT)');db.commit()
            self.assertFalse(paused(path))
            db.execute('INSERT INTO state VALUES(?,?)',('control',json.dumps(dict(paused=True))));db.commit()
            self.assertTrue(paused(path))
            db.execute('UPDATE state SET value=?',(json.dumps(dict(paused=False)),));db.commit()
            self.assertFalse(paused(path))
            db.execute('UPDATE state SET value=?',('invalid',));db.commit()
            self.assertTrue(paused(path));db.close()

    def test_control_cost_gate_and_cash_abstention(self):
        row=dict(symbol='SOLUSDT',ts=100000,session='s',x=[0.]*len(FEATURES))
        self.assertEqual(signals(row,'cash'),[])
        self.assertLess(signals(row,'momentum')[0]['expected_net_return'],0)
        self.assertEqual(signals(row,'leadlag_flow'),[])
        row['x'][FEATURES.index('btc_30s')]=.01
        row['x'][FEATURES.index('eth_30s')]=.01
        row['x'][FEATURES.index('flow_5s')]=.8
        row['x'][FEATURES.index('volatility_acceleration')]=.001
        self.assertGreater(signals(row,'leadlag_flow')[0]['expected_net_return'],0)

    def test_complete_recorded_roundtrip_replays_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'paper.db';db=DurablePaper(path)
            db.apply('d',dict(type='decision',now_ms=100000,signals=[signal()]))
            for t in range(101000,113000,1000):
                db.apply(str(t),dict(type='book',row=book(t)),INST)
            db.close();result=audit(path)
            self.assertTrue(result['operational_pass']);self.assertEqual(result['trades'],1)
            self.assertFalse(result['financial_qualified'])
            db=sqlite3.connect(path)
            state=json.loads(db.execute('SELECT state FROM account').fetchone()[0]);state['cash']+=1
            db.execute('UPDATE account SET state=?',(json.dumps(state),));db.commit();db.close()
            with self.assertRaises(ValueError):audit(path)


if __name__=='__main__':unittest.main()
