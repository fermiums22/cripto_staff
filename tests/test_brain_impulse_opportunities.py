import unittest
import numpy as np
from brain_impulse_opportunities import thresholds,masks,thin


class OpportunityTests(unittest.TestCase):
    def test_masks_causal_and_side_symmetric(self):
        rng=np.random.default_rng(1);x=rng.normal(size=(100,30));cut=thresholds(x)
        original=masks(x,1,cut);mirror=x.copy()
        mirror[:,[0,1,4,7,8,13,21,22]]*=-1
        for k,v in masks(mirror,-1,cut).items():np.testing.assert_array_equal(v,original[k])
        later=np.vstack([x,np.full((10,30),10000.)])
        for k,v in masks(later,1,cut).items():np.testing.assert_array_equal(v[:100],original[k])

    def test_thinning_does_not_use_outcomes(self):
        t=np.arange(0,600001,5000);mask=np.ones(len(t),dtype=bool)
        ids=thin(t,mask);np.testing.assert_array_equal(t[ids],[0,180000,360000,540000])


if __name__=='__main__':unittest.main()
