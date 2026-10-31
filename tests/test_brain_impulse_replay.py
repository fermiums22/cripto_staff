import unittest
from brain_impulse_replay import replay
from test_brain_impulse_execution import book,signal,INST


def events(stop=False):
    for t in range(100000,115001,250):
        q=book(t,bid=97 if stop and t>=102000 else 99.9,ask=97.1 if stop and t>=102000 else 100.)
        yield dict(ts=t,book=q,sample=dict(q,x=[]) if t==100000 else None)


class ReplayTests(unittest.TestCase):
    def run_replay(self,stop=False):
        return replay(events(stop),{'model':lambda r:[signal(r['ts'])],'cash':lambda r:[]},INST,100000,400000)

    def test_real_depth_latency_fees_and_cash_control(self):
        result=self.run_replay();r=result['reports']['model'];trade=r['trades_detail'][0]
        self.assertEqual(trade['decision_ms'],100500)
        self.assertEqual(trade['opened_ms'],101500)
        self.assertEqual(trade['closed_ms'],112500)
        self.assertLess(r['net_pnl'],0);self.assertGreater(r['fees'],0)
        self.assertTrue(r['execution_valid']);self.assertFalse(result['independent_paper_evidence'])
        self.assertEqual(result['reports']['cash']['net_pnl'],0)

    def test_stop_observes_books_between_feature_samples(self):
        r=self.run_replay(True)['reports']['model'];t=r['trades_detail'][0]
        self.assertEqual(t['reason'],'stop');self.assertEqual(t['closed_ms'],103000)
        self.assertGreater(r['mark_to_market_drawdown'],.01)

    def test_truncated_position_is_not_fictitiously_closed(self):
        result=replay(list(events())[:9],{'model':lambda r:[signal(r['ts'])]},INST,100000,400000)
        r=result['reports']['model'];self.assertEqual(r['trades'],0)
        self.assertFalse(r['execution_valid']);self.assertIn('unresolved_end_state',r['evidence_issues'])

    def test_future_forecast_and_clock_regression_rejected(self):
        with self.assertRaises(ValueError):
            replay(events(),{'bad':lambda r:[signal(r['ts']+1)]},INST,100000,400000)
        with self.assertRaises(ValueError):
            replay(reversed(list(events())),{'cash':lambda r:[]},INST,100000,400000)


if __name__=='__main__':unittest.main()
