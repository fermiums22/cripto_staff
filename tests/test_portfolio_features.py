import copy
import importlib.util
import unittest
import numpy as np
from test_portfolio import market

HAS_TORCH=importlib.util.find_spec('torch') is not None
if HAS_TORCH:
    import torch
    from portfolio_research import build_features,Experts


@unittest.skipUnless(HAS_TORCH,'Optional sequence research dependencies not installed')
class SequenceTests(unittest.TestCase):
    def test_no_future_features_or_future_funding(self):
        m=market();m['BTCUSDT']=m.pop('ALTUSDT');m['ETHUSDT']=m.pop('OTHERUSDT')
        before=build_features(m)
        changed=copy.deepcopy(m)
        for s in changed:
            changed[s]['trade'][140][4]*=2
            changed[s]['funding']=[dict(fundingRateTimestamp=str(145*900000),fundingRate='.5')]
        after=build_features(changed)
        for s in m:np.testing.assert_array_equal(before[s][:140],after[s][:140])

    def test_gate_and_real_gradient_update(self):
        torch.manual_seed(42);model=Experts();x=torch.randn(8,16,14)
        before=[p.detach().clone() for p in model.parameters()]
        y,w=model(x);torch.testing.assert_close(w.sum(1),torch.ones(8))
        optimizer=torch.optim.Adam(model.parameters(),lr=.01)
        loss=(y-1).square().mean();optimizer.zero_grad();loss.backward();optimizer.step()
        self.assertTrue(any(not torch.equal(a,b) for a,b in zip(before,model.parameters())))


if __name__=='__main__':unittest.main()
