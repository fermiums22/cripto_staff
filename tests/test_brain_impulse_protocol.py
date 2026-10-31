import unittest
import numpy as np
from brain_impulse_protocol import DAY, ResearchPolicy, development_mask, coverage, walk_forward, trade_report


class ProtocolTests(unittest.TestCase):
    def test_reservation_excludes_labels_crossing_start(self):
        result=development_mask([1,5,10,20],[4,11,19,25],[(10,20)])
        self.assertEqual(result.tolist(),[True,False,False,True])

    def test_burst_cannot_count_as_covered_day(self):
        rows=[dict(symbol=s,ts=d*DAY+h*3600000+i)
              for d in range(21) for h in range(24) for s in ('A','B','C','D') for i in range(2)]
        self.assertFalse(coverage(rows)['admission'])

    def test_days_must_be_contiguous(self):
        policy=ResearchPolicy(minimum_development_days=3,minimum_hours_per_day=1,
                              minimum_minutes_per_hour=1,minimum_symbols=1)
        rows=[dict(symbol='A',ts=d*DAY) for d in (0,2,4)]
        self.assertFalse(coverage(rows,policy)['admission'])
        rows=[dict(symbol='A',ts=d*DAY) for d in (0,1,2)]
        self.assertTrue(coverage(rows,policy)['admission'])

    def test_folds_purge_label_and_feature_overlap(self):
        ts=np.arange(0,29*DAY,60000);end=ts+120000
        folds=walk_forward(ts,end,0)
        self.assertEqual(len(folds),2)
        for train,valid,test in folds:
            self.assertLess(end[train[-1]]+180000,ts[valid[0]])
            self.assertLess(end[valid[-1]]+180000,ts[test[0]])

    def test_report_has_cash_days_and_coin_concentration(self):
        rows=[dict(symbol='A',closed_ms=DAY,net_pnl=1.,fees=.1),
              dict(symbol='B',closed_ms=2*DAY,net_pnl=-.5,fees=.2)]
        r=trade_report(rows,0,7*DAY)
        self.assertEqual(len(r['daily_pnl']),7)
        self.assertEqual(r['net_pnl'],.5)
        self.assertEqual(r['pnl_without_best_symbol'],-.5)
        self.assertFalse(r['ready'])
        self.assertLess(r['mean_daily_95ci'][0],0)


if __name__ == '__main__':unittest.main()
