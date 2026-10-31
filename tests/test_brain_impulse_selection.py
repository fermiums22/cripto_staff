import copy
import unittest
from brain_impulse_selection import select,aggregate,MODELS,CONTROLS


def folds(profit=0.,symbol=None):
    result=[]
    for days in ([1,2],[3,4,5]):
        trades=[dict(symbol=symbol or ('SOL','DOGE','XRP')[i%3],closed_ms=d*86400000+1000+i,
                     net_pnl=profit,fees=.001) for d in days for i in range(20)] if profit else []
        total=sum(t['net_pnl'] for t in trades)
        result.append(dict(days=list(days),report=dict(execution_valid=True,evidence_issues=[],
            daily_pnl=[20*profit for d in days],net_pnl=total,fees=sum(t['fees'] for t in trades),
            trades=len(trades),trades_detail=trades,mark_to_market_drawdown=.01)))
    return result


def fixture():
    return {name:{'base':folds(.01 if name=='ridge' else -.01 if name in MODELS else 0),
                  'stress':folds(.005 if name=='ridge' else -.015 if name in MODELS else 0)}
            for name in MODELS+CONTROLS}


class SelectionTests(unittest.TestCase):
    def test_diagnostic_only_pass_never_live_promotion(self):
        result=select(fixture())
        self.assertEqual(result['selected_for_diagnostic'],'ridge')
        self.assertFalse(result['ready']);self.assertFalse(result['live_promotion_allowed'])
        self.assertTrue(result['results']['mlp']['rejected'])

    def test_one_coin_and_negative_stress_are_rejected(self):
        data=fixture();data['ridge']['base']=folds(.01,symbol='LUCKY')
        self.assertEqual(select(data)['selected_for_diagnostic'],'CASH')
        data=fixture();data['ridge']['stress']=folds(-.001)
        self.assertIn('stress_nonpositive_fold',select(data)['results']['ridge']['reasons'])

    def test_no_trade_day_and_one_day_bootstrap_cannot_pass(self):
        data=fixture()
        for scenarios in data.values():
            for name,values in scenarios.items():
                scenarios[name]=[values[0]]
        result=select(data)
        self.assertIn('insufficient_calendar_days',result['results']['ridge']['reasons'])
        self.assertEqual(result['selected_for_diagnostic'],'CASH')

    def test_missing_control_or_misaligned_or_forged_ledger_fails(self):
        data=fixture();data.pop('cash')
        with self.assertRaises(ValueError):select(data)
        data=fixture();data['cash']['base'][0]['days']=[8,9]
        with self.assertRaises(ValueError):select(data)
        data=fixture();data['ridge']['base'][0]['report']['fees']+=.1
        with self.assertRaises(ValueError):select(data)

    def test_positive_cash_pnl_requires_paired_advantage(self):
        data=fixture();data['momentum']['base']=folds(.02)
        self.assertIn('no_paired_advantage_momentum',select(data)['results']['ridge']['reasons'])
        data=fixture();data['cash']['base'][0]['report']['execution_valid']=False
        self.assertIn('invalid_control_cash',select(data)['results']['ridge']['reasons'])


if __name__=='__main__':unittest.main()
