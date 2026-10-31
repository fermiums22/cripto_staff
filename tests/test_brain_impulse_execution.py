import copy
from dataclasses import replace
import tempfile
from pathlib import Path
import unittest
from brain_impulse_execution import ExecutionPolicy, DurablePaper, initial_state, decide, on_book, rank

INST={'SOLUSDT':{'status':'Trading','lotSizeFilter':{'qtyStep':'.001','minOrderQty':'.001',
      'maxMktOrderQty':'100','minNotionalValue':'5'}}}


def book(stamp=100000,bid=99.9,ask=100.,session='s'):
    return dict(ts=stamp,event_ms=stamp-10,symbol='SOLUSDT',session=session,
                bids=[[bid,.05],[bid-.1,10]],asks=[[ask,.05],[ask+.1,10]])


def signal(stamp=100000,side=1,score=.01):
    return dict(symbol='SOLUSDT',observed_ms=stamp,side=side,horizon_ms=10000,
                expected_net_return=score,session='s')


class ExecutionTests(unittest.TestCase):
    def test_rank_uses_net_edge_and_past_only(self):
        a=signal(score=.005);b=dict(signal(score=.008),symbol='XRPUSDT')
        self.assertEqual(rank([a,b],100000)['symbol'],'XRPUSDT')
        b['observed_ms']=100001
        self.assertEqual(rank([a,b],100000)['symbol'],'SOLUSDT')
        a['uncertainty']=.006
        self.assertIsNone(rank([a,b],100000))

    def test_no_same_quote_entry_or_exit_and_depth_fees(self):
        s=initial_state();decide(s,[signal()],100000)
        on_book(s,book(100000),INST);self.assertIsNone(s['position'])
        on_book(s,book(101000),INST);self.assertIsNotNone(s['position'])
        self.assertGreater(s['position']['entry_notional']/s['position']['qty'],100)
        for t in range(102000,112000,1000):on_book(s,book(t),INST)
        self.assertEqual(s['pending']['kind'],'exit');self.assertEqual(len(s['trades']),0)
        on_book(s,book(112000),INST)
        self.assertIsNone(s['position']);self.assertEqual(len(s['trades']),1)
        tr=s['trades'][0]
        self.assertAlmostEqual(s['cash']-15,tr['net_pnl'])
        self.assertAlmostEqual(tr['fees'],.0006*(tr['entry_notional']+tr['exit_notional']))
        self.assertEqual(tr['entry_delay_ms'],1000);self.assertEqual(tr['exit_delay_ms'],1000)
        self.assertLess(tr['net_pnl'],0)

    def test_pause_cancels_entry_but_does_not_block_exit(self):
        s=initial_state();decide(s,[signal()],100000)
        on_book(s,book(101000),INST,paused=True);self.assertIsNone(s['position'])
        decide(s,[signal(102000)],102000);on_book(s,book(103000),INST)
        on_book(s,book(104000,bid=95,ask=95.1),INST,paused=True)
        self.assertEqual(s['pending']['reason'],'stop')
        on_book(s,book(105000,bid=95,ask=95.1),INST,paused=True)
        self.assertIsNone(s['position'])

    def test_drawdown_marks_open_positions_and_reduces_future_size(self):
        s=initial_state();decide(s,[signal()],100000);on_book(s,book(101000),INST)
        first=s['position']['entry_notional']
        on_book(s,book(102000,bid=97,ask=97.1),INST)
        self.assertGreater(s['max_drawdown'],.02)
        on_book(s,book(103000,bid=97,ask=97.1),INST)
        decide(s,[signal(104000)],104000);on_book(s,book(105000),INST)
        self.assertLess(s['position']['entry_notional'],first)

    def test_reconnect_cancels_pending_entry(self):
        s=initial_state();decide(s,[signal()],100000)
        on_book(s,book(101000,session='new'),INST)
        self.assertIsNone(s['position']);self.assertIsNone(s['pending'])

    def test_gap_does_not_reset_position_and_invalidates_evidence(self):
        s=initial_state();decide(s,[signal()],100000);on_book(s,book(101000),INST)
        on_book(s,book(120000,session='new'),INST)
        self.assertIsNotNone(s['position']);self.assertTrue(s['halted'])
        self.assertIn('position_data_gap',s['evidence_issues'])
        on_book(s,book(121000,session='new'),INST);self.assertIsNone(s['position'])

    def test_unresolved_funding_never_becomes_free_profit_evidence(self):
        s=initial_state();decide(s,[signal()],100000);on_book(s,book(101000),INST)
        on_book(s,book(3601000),INST)
        self.assertIn('unresolved_funding',s['evidence_issues']);self.assertTrue(s['halted'])

    def test_funding_boundary_and_instrument_minimum_reject(self):
        s=initial_state();decide(s,[signal(3599000)],3599000)
        self.assertIsNone(s['pending'])
        s=initial_state();decide(s,[signal()],100000)
        inst=copy.deepcopy(INST);inst['SOLUSDT']['lotSizeFilter']['minNotionalValue']='20'
        on_book(s,book(101000),inst);self.assertIsNone(s['position'])

    def test_durable_restart_and_idempotence(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'paper.db';db=DurablePaper(path)
            event=dict(type='decision',now_ms=100000,signals=[signal()])
            self.assertTrue(db.apply('intent1',event));self.assertFalse(db.apply('intent1',event))
            with self.assertRaises(ValueError):db.apply('intent1',dict(event,now_ms=100001))
            db.apply('book1',dict(type='book',row=book(101000)),INST)
            before=db.state();db.close();db=DurablePaper(path)
            self.assertEqual(db.state(),before)
            for t in range(102000,113000,1000):
                db.apply(str(t),dict(type='book',row=book(t)),INST)
            self.assertEqual(len(db.trades()),1)
            self.assertAlmostEqual(db.state()['cash']-15,db.trades()[0]['net_pnl'])
            self.assertEqual(db.state()['closed_trades'],1);db.close()
            with self.assertRaises(ValueError):DurablePaper(path,replace(ExecutionPolicy(),fee=.0001))
            with self.assertRaises(ValueError):DurablePaper(path,protocol_id='reset_attempt')

    def test_invalid_transaction_rolls_back(self):
        with tempfile.TemporaryDirectory() as temp:
            db=DurablePaper(Path(temp)/'paper.db');before=db.state()
            with self.assertRaises(ValueError):db.apply('bad',dict(type='unknown'))
            self.assertEqual(db.state(),before)
            self.assertEqual(db.db.execute('SELECT count(*) FROM processed').fetchone()[0],0)
            db.close()


if __name__=='__main__':unittest.main()
