import importlib.util
import unittest
from unittest.mock import patch
import numpy as np
from test_portfolio import market
from qusdt_microstructure import execution_proxy
HAS_TORCH=importlib.util.find_spec('torch') is not None
if HAS_TORCH:
    from ranker_research import fit_ranker,rank_signals,enhanced


class PrintProxyTests(unittest.TestCase):
    def test_latency_side_and_participation(self):
        prints=[[100,1.,100.,1],[250,2.,20.,1],[300,9.,200.,-1],[1000,4.,20.,1]]
        result=execution_proxy(prints,1,3,0)
        self.assertTrue(result['filled']);self.assertAlmostEqual(result['vwap'],8/3)
        self.assertEqual(result['completion_ms'],1000)

    def test_unfilled_is_explicit(self):
        result=execution_proxy([[300,2.,10.,1],[6000,2.,1000.,1]],1,3,0)
        self.assertFalse(result['filled']);self.assertAlmostEqual(result['filled_qty'],1)


@unittest.skipUnless(HAS_TORCH,'Optional research dependencies needed')
class RankingTests(unittest.TestCase):
    def test_training_groups_and_excluded_symbols(self):
        captured={}
        class Fake:
            def __init__(self,**kwargs):pass
            def fit(self,x,y,qid):captured.update(x=x,y=y,qid=qid)
            def get_booster(self):return self
            def save_config(self):return '{"learner":{"generic_param":{"device":"cuda:0"}}}'
        m=market();x={s:np.full((260,18),j+1.) for j,s in enumerate(m)}
        with patch('ranker_research.XGBRanker',Fake):fit_ranker(m,x,['SOLUSDT'],140,.001)
        self.assertTrue(np.all(np.diff(captured['qid'])>=0))
        self.assertTrue(np.all(np.unique(captured['qid'],return_counts=True)[1]==3))
        self.assertEqual(set(captured['x'][:,0]),{0.,1.})
        cash=captured['x'][:,-1]==1
        self.assertTrue(np.all(captured['y'][cash]==1))

    def test_ranker_cash_top_three_and_heldout(self):
        scores={str(i):np.array([[0.,float(i)]]) for i in range(6)}
        signals,priority=rank_signals(scores,1.,list(scores),.5)
        self.assertEqual({s for s,v in signals.items() if v[0]}, {'3','4','5'})
        signals,_=rank_signals(scores,9.,list(scores),0)
        self.assertFalse(any(v[0] for v in signals.values()))
        signals,_=rank_signals(scores,1.,['5'],0)
        self.assertEqual({s for s,v in signals.items() if v[0]}, {'5'})

    def test_acceleration_does_not_use_future(self):
        m=market();raw={s:np.zeros((260,14),dtype=np.float32) for s in m}
        before=enhanced(raw,m);raw['SOLUSDT'][150,4]=20
        after=enhanced(raw,m)
        np.testing.assert_array_equal(before['SOLUSDT'][:150],after['SOLUSDT'][:150])


if __name__=='__main__':unittest.main()
