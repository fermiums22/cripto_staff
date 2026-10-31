import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from brain_impulse_diagnostic import assess,run
from brain_impulse_selection import CONTROLS


def report(profit):
    trades=[dict(closed_ms=d*86400000+1000+i,symbol=('A','B','C')[i%3],net_pnl=profit,fees=.001)
            for d in range(1,8) for i in range(20)] if profit else []
    return dict(execution_valid=True,evidence_issues=[],daily_pnl=[20*profit]*7,
        net_pnl=sum(t['net_pnl'] for t in trades),fees=sum(t['fees'] for t in trades),
        trades=len(trades),trades_detail=trades,mark_to_market_drawdown=.01)


class DiagnosticTests(unittest.TestCase):
    def test_only_future_paper_eligibility_never_readiness(self):
        reports={scenario:{k:report(.01 if k=='ridge' else 0.) for k in ('ridge',)+CONTROLS} for scenario in ('base','stress')}
        result=assess(reports,'ridge',list(range(1,8)))
        self.assertTrue(result['eligible_for_new_future_paper']);self.assertFalse(result['ready'])
        self.assertFalse(result['independent_paper_evidence']);self.assertFalse(result['live_promotion_allowed'])
        reports['stress']['ridge']=report(-.01)
        self.assertFalse(assess(reports,'ridge',list(range(1,8)))['eligible_for_new_future_paper'])

    def test_cash_decision_never_opens_final_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            with patch('brain_impulse_diagnostic.validate',return_value={'selected_for_diagnostic':'CASH'}),patch('brain_impulse_diagnostic.plans_for_fold') as plans:
                run(out/'nonexistent-campaign',out)
                plans.assert_not_called()
                self.assertIn('final_data_unopened',(out/'diagnostic-status.json').read_text())


if __name__=='__main__':unittest.main()
