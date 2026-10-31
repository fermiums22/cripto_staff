import copy
import unittest
import numpy as np
import torch
from brain_evolution_env import ExplorationAccount
from brain_evolution_policy import population,evolve,outputs,fitness
from brain_evolution_lab import replay

INST={'SOLUSDT':{'lotSizeFilter':{'qtyStep':'.001','minOrderQty':'.001','minNotionalValue':'1'}}}

def book(t,price=100):return dict(ts=t,symbol='SOLUSDT',bids=[(price-.01,1000)],asks=[(price+.01,1000)])
def buy(**kw):return dict(kind='BUY',symbol='SOLUSDT',fraction=.8,leverage=1.,stop=.1,hold_ms=60000,**kw)


class EvolutionTests(unittest.TestCase):
    @unittest.skipUnless(torch.cuda.is_available(),'CUDA required')
    def test_cuda_policy_outputs_and_evolution_change_parameters(self):
        pop=population();c=next(c for c in pop if c['architecture']=='moe')
        x=np.random.default_rng(7).normal(size=(128,30)).astype('float32')
        cpu=outputs(c,x,np.zeros(30),np.ones(30),'cpu')
        gpu=outputs(c,x,np.zeros(30),np.ones(30),'cuda')
        np.testing.assert_allclose(cpu,gpu,atol=1e-5,rtol=1e-4)
        reports={c['id']:dict(net_return=-.1,max_drawdown=.2,evidence_issues=[]) for c in pop}
        children=evolve(pop,reports,1,7301);parents={c['id']:c for c in pop}
        mutations=[c for c in children if c['architecture']!='rule' and any(not torch.equal(v,parents[c['parent']]['weights'][k]) for k,v in c['weights'].items())]
        self.assertGreater(len(mutations),0)

    def test_delayed_entry_close_and_after_cost_feedback(self):
        a=ExplorationAccount(INST);a.act(buy(),100000)
        a.book(book(100999));self.assertIsNone(a.position)
        a.book(book(101000));self.assertIsNotNone(a.position)
        a.act({'kind':'HOLD'},102000);a.act({'kind':'CLOSE'},103000)
        a.book(book(103999,102));self.assertIsNotNone(a.position)
        a.book(book(104000,102));r=a.report()
        self.assertEqual(r['trades'],1);self.assertGreater(r['net_pnl'],0)
        self.assertAlmostEqual(r['net_pnl'],r['trades_detail'][0]['gross_pnl']-r['fees'])
        self.assertAlmostEqual(r['accounting_residual'],0);self.assertFalse(r['ready'])

    def test_liquidation_and_cash_baseline_no_reward_for_count(self):
        a=ExplorationAccount(INST);order=buy();order.update(leverage=10.,fraction=1.)
        a.act(order,100000);a.book(book(101000));a.book(book(102000,89))
        r=a.report();self.assertEqual(r['liquidations'],1);self.assertTrue(r['bankrupt'])
        self.assertLess(fitness(r,0),0);self.assertEqual(fitness(ExplorationAccount(INST).report(),1),0)

    def test_population_selection_uses_financial_result_and_preserves_parent(self):
        pop=population();reports={c['id']:dict(net_return=-.1,max_drawdown=.2,evidence_issues=[]) for c in pop}
        winner=next(c for c in pop if c['id']=='momentum-aggressive-g0')
        reports[winner['id']]['net_return']=.2
        children=evolve(pop,reports,1,7301)
        chosen=[c for c in children if c['family']=='momentum']
        self.assertTrue(all(c['parent']==winner['id'] for c in chosen))
        self.assertEqual(chosen[0]['leverage'],winner['leverage'])
        self.assertEqual(winner['generation'],0)
        original=next(c for c in pop if c['architecture']=='mlp')
        x=np.random.default_rng(4).normal(size=(20,30)).astype('float32')
        self.assertEqual(outputs(original,x,np.zeros(30),np.ones(30),'cpu').shape,(20,7))

    def test_replay_trades_without_production_edge_gate(self):
        t=np.arange(100000,500000,1000,dtype='int64');price=100+np.sin(np.arange(len(t))*.03)
        depth=np.zeros((len(t),2,10,2));depth[:,0,0,0]=price-.01;depth[:,1,0,0]=price+.01;depth[:,:,0,1]=1000
        ft=t[::5]+1;x=np.zeros((len(ft),30),dtype='float32');x[:,1]=.001
        tape=dict(bt=t,bs=np.zeros(len(t),dtype='int8'),depth=depth,ft=ft,fs=np.zeros(len(ft),dtype='int8'),fx=x)
        pop=[c for c in population() if c['id'] in ('cash-g0','momentum-g0')]
        r=replay(tape,pop,INST,np.zeros(30),np.ones(30),'cpu')
        self.assertEqual(r['cash-g0']['trades'],0);self.assertGreater(r['momentum-g0']['trades'],0)
        self.assertEqual(r['momentum-g0']['evidence_issues'],[])


if __name__=='__main__':unittest.main()
