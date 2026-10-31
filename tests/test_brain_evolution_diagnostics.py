import unittest
import numpy as np
import torch
from brain_evolution_attribution import attribute
from brain_evolution_env import ExplorationAccount
from brain_evolution_experts import Experts,objective,grid


class DiagnosticsTests(unittest.TestCase):
    def test_attribution_long_and_short_reconciles_all_costs(self):
        instruments={'SOLUSDT':{'lotSizeFilter':{'qtyStep':'.001','minOrderQty':'.001','minNotionalValue':'1'}}}
        for side in (1,-1):
            a=ExplorationAccount(instruments);order=dict(kind='BUY' if side==1 else 'SELL',symbol='SOLUSDT',fraction=.8,leverage=1.,stop=.1,hold_ms=60000)
            a.act(order,100000);times=np.arange(100000,106000,1000,dtype='int64');levels=[]
            for t in times:
                price=100+side*(t-100000)/2000
                book=dict(ts=int(t),symbol='SOLUSDT',bids=[(price-.02,100)],asks=[(price+.02,100)])
                levels.append([book['bids'],book['asks']])
                if t==103000:a.act({'kind':'CLOSE'},int(t))
                a.book(book)
            tape=dict(bt=times,bs=np.zeros(len(times),dtype='int8'),depth=np.asarray(levels),ft=np.array([100000]),fs=np.array([0]),fx=np.zeros((1,30)))
            rows=attribute(a.trades,a.actions,tape);self.assertEqual(len(rows),1)
            row=rows[0];self.assertAlmostEqual(row['identity_error'],0)
            self.assertGreater(row['spread_cost'],0);self.assertGreater(row['slippage_cost'],0)
            self.assertLess(row['net_mae'],0);self.assertGreaterEqual(row['net_mfe']+1e-10,row['net_pnl'])

    def test_proxy_charges_entry_and_final_exit_and_rewards_cash_zero(self):
        weights=torch.full((2,10,4),.25);ret=torch.zeros_like(weights);cost=torch.full_like(weights,.001)
        net,fees=objective(weights,ret,cost)
        torch.testing.assert_close(net,torch.full((2,),-.002))
        torch.testing.assert_close(fees,torch.full((2,),.002))
        net,_=objective(torch.zeros_like(weights),ret,cost);self.assertTrue((net==0).all())
        weights=torch.full((2,120,4),.25)
        net,fees=objective(weights,torch.zeros_like(weights),torch.full_like(weights,.001))
        torch.testing.assert_close(fees,torch.full((2,),.004))

    def test_observation_mask_does_not_depend_on_future_quotes(self):
        times=np.repeat(np.arange(100000,150000,1000,dtype='int64'),4);symbols=np.tile(np.arange(4),50)
        depth=np.ones((len(times),2,1,2));depth[:,0,0,0]=99.;depth[:,1,0,0]=101.;depth[:,:,:,1]=100
        ft=np.repeat(np.arange(100000,150000,5000,dtype='int64'),4)
        tape=dict(bt=times,bs=symbols,depth=depth,ft=ft,fs=np.tile(np.arange(4),10),fx=np.ones((len(ft),30)))
        original=grid(tape);keep=~np.isin(times,[106000,107000])
        changed=grid(dict(tape,bt=times[keep],bs=symbols[keep],depth=depth[keep]))
        self.assertFalse(np.array_equal(original['valid'],changed['valid']))
        np.testing.assert_array_equal(original['observed'],changed['observed'])
        np.testing.assert_array_equal(original['x'],changed['x'])

    @unittest.skipUnless(torch.cuda.is_available(),'CUDA required')
    def test_actual_architectures_receive_finite_financial_gradients(self):
        for kind in ('direct','experts'):
            torch.manual_seed(3);model=Experts(kind).cuda();x=torch.randn(8,32,4,30,device='cuda')
            returns=.01*x[...,0].tanh();cost=torch.zeros_like(returns);opt=torch.optim.SGD(model.parameters(),lr=.1)
            before=float(-objective(model(x)[0],returns,cost)[0].mean().detach())
            for _ in range(5):
                opt.zero_grad();loss=-objective(model(x)[0],returns,cost)[0].mean();loss.backward()
                self.assertTrue(all(p.grad is None or torch.isfinite(p.grad).all() for p in model.parameters()));opt.step()
            after=float(-objective(model(x)[0],returns,cost)[0].mean().detach());self.assertLess(after,before)


if __name__=='__main__':unittest.main()
