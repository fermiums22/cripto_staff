import unittest
from random_brackets import hit,simulate
from test_window_experiment import data


class RandomBracketTests(unittest.TestCase):
    def test_stop_first_for_both_directions_and_gaps(self):
        self.assertEqual(hit([0,100,102,98,100],1,100,.01,.01),(99,'stop'))
        self.assertEqual(hit([0,100,102,98,100],-1,100,.01,.01),(101,'stop'))
        self.assertEqual(hit([0,103,103,99,100],-1,100,.01,.01),(103,'stop'))

    def test_flat_market_only_costs_and_terminal_exit(self):
        d=data(50);r=simulate(d,0,50,.01,.003,1)
        self.assertEqual(r['trades'],1)
        self.assertLess(r['end_equity'],10)
        self.assertAlmostEqual(r['curve'][-1][1],r['end_equity'])
        self.assertEqual(r,simulate(d,0,50,.01,.003,1))
