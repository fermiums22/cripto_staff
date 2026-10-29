import unittest
from window_experiment import equity,simulate


def data(minutes=180):
    rows=[[i*60000,100,100,100,100] for i in range(minutes)]
    return dict(trade=rows,mark=[r[:] for r in rows],end_ms=rows[-1][0],funding=[],
        instrument=dict(lotSizeFilter=dict(qtyStep='.01',minOrderQty='.01',minNotionalValue='5')),
        risk=dict(maintenanceMargin=.005,mmDeduction='0'))


class WindowTests(unittest.TestCase):
    def test_equal_hedge_does_not_earn_from_price_movement(self):
        p=[dict(side=1,qty=1,entry=100),dict(side=-1,qty=1,entry=100)]
        self.assertEqual(equity(10,p,90,0,0),10)
        self.assertEqual(equity(10,p,120,0,0),10)

    def test_margin_bounded_no_fictitious_profit_terminal_positions_counted(self):
        result=simulate(data(),1)
        self.assertLessEqual(result['peak_windows'],4)
        self.assertLess(result['end_equity'],10)
        self.assertEqual(result['entries'],result['exits'])
        self.assertGreater(result['terminal_positions'],0)
        self.assertEqual(result['basket_wins'],0)
        self.assertEqual(result,simulate(data(),1))

    def test_funding_is_charged_once_to_existing_position(self):
        d=data(20);base=simulate(d,1)
        d['funding']=[dict(fundingRateTimestamp='600000',fundingRate='.001')]
        r=simulate(d,1)
        self.assertNotEqual(r['funding'],0)
        self.assertAlmostEqual(r['end_equity']-base['end_equity'],r['funding'])

    def test_adverse_mark_triggers_liquidation_before_price_stop(self):
        d=data(2)
        # Seed 1 opens short. Mark jump affects liquidation even if trade is flat.
        d['mark'][1]=[60000,100,200,100,200]
        r=simulate(d,1)
        self.assertEqual(r['liquidations'],1)
        self.assertEqual(r['terminal_positions'],0)

    def test_nested_requires_adverse_move_and_never_exceeds_window_cap(self):
        settings=dict(mode='average',trigger=.003,multiplier=2)
        flat=simulate(data(),1,nested=settings)
        self.assertEqual(flat['entries'],1)
        d=data()
        for i,row in enumerate(d['trade']):
            price=100*(1+min(i,70)*.001)
            row[1:]=[price]*4;d['mark'][i][1:]=[price]*4
        r=simulate(d,1,nested=settings)
        self.assertGreater(r['entries'],1)
        self.assertLessEqual(r['peak_windows'],4)
        self.assertGreater(r['blocked_minutes'],0)
        self.assertEqual(r['entries'],r['exits'])
