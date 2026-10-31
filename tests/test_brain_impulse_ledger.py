from pathlib import Path
import tempfile
import unittest
import json
from brain_impulse_ledger import BatchPaper
from brain_impulse_group_audit import audit
from brain_impulse_execution import DurablePaper
from test_brain_impulse_execution import INST,book,signal


class BatchLedgerTests(unittest.TestCase):
    def test_equivalent_to_single_accounts_after_restart_and_trades(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);batch=BatchPaper(p/'batch.db',('a','b'),'test')
            singles={n:DurablePaper(p/(n+'.db'),protocol_id='test') for n in ('a','b')}
            events=[dict(type='decision',now_ms=100000,signals=[signal()])]
            events += [dict(type='book',row=book(t)) for t in range(101000,113000,1000)]
            for i,event in enumerate(events):
                group={n:event for n in singles};self.assertTrue(batch.apply(str(i),group,INST))
                for db in singles.values():db.apply(str(i),event,INST)
                if i==4:batch.close();batch=BatchPaper(p/'batch.db',('b','a'),'test')
            for name,db in singles.items():
                self.assertEqual(batch.states()[name],db.state());self.assertEqual(batch.trades(name),db.trades());db.close()
            self.assertEqual(len(batch.trades('a')),1)
            self.assertFalse(batch.apply(str(len(events)-1),{n:events[-1] for n in singles},INST));batch.close()
            result=audit(p/'batch.db');self.assertTrue(result['operational_pass'])
            self.assertFalse(result['financial_qualified']);self.assertEqual(result['accounts']['a']['trades'],1)

    def test_independent_audit_detects_state_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'batch.db';db=BatchPaper(path,('a','b'),'test')
            db.apply('one',{'a':dict(type='decision',now_ms=1,signals=[])})
            state=db.states()['a'];state['cash']+=1
            with db.db:db.db.execute('UPDATE accounts SET state=? WHERE name=?',(json.dumps(state),'a'))
            db.close()
            with self.assertRaises(ValueError):audit(path)

    def test_failure_rolls_back_every_account_and_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=BatchPaper(Path(tmp)/'batch.db',('a','b'),'test');before=db.states()
            with self.assertRaises(ValueError):db.apply('fail',{'a':dict(type='decision',now_ms=1,signals=[]),'b':dict(type='invalid')})
            self.assertEqual(db.states(),before)
            self.assertEqual(db.db.execute('SELECT count(*) FROM batches').fetchone()[0],0)
            db.apply('one',{'a':dict(type='decision',now_ms=1,signals=[])})
            with self.assertRaises(ValueError):db.apply('one',{'a':dict(type='decision',now_ms=2,signals=[])})
            db.close()

    def test_existing_wallet_and_protocol_cannot_be_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);old=DurablePaper(p/'old.db');old.close()
            with self.assertRaises(ValueError):BatchPaper(p/'old.db',('a',),'test')
            batch=BatchPaper(p/'batch.db',('a',),'test');batch.close()
            with self.assertRaises(ValueError):BatchPaper(p/'batch.db',('a','b'),'test')
            with self.assertRaises(ValueError):BatchPaper(p/'batch.db',('a',),'changed')


if __name__=='__main__':unittest.main()
