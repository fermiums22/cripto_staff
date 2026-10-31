import unittest
import numpy as np
from brain_impulse_rare import average_precision,features,chosen


class RareTests(unittest.TestCase):
    def test_average_precision_handles_ties_and_absent_events(self):
        self.assertEqual(average_precision([1,0,1,0],[0,0,0,0]),.5)
        self.assertEqual(average_precision([1,0],[2,1]),1.)
        self.assertIsNone(average_precision([0,0],[1,2]))

    def test_selection_has_no_access_to_outcomes(self):
        n=100;d=dict(t=np.arange(n)*5000,x=np.zeros((n,30)),symbols=np.zeros(n,dtype='int8'),y=np.zeros((n,8)))
        score=np.ones(n);side=np.zeros(n,dtype='int64');before=chosen(d,score,side,.5)
        d['y'][:]=100;after=chosen(d,score,side,.5)
        self.assertEqual(before['sample_indices'],after['sample_indices'])
        self.assertEqual(features(d,np.zeros(30),np.ones(30)).shape,(n,34))


if __name__=='__main__':unittest.main()
