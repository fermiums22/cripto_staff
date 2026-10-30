import json
import pathlib
import tempfile
import unittest
import numpy as np
import torch
from brain_microstructure import Sampler
from brain_micro_validation import labelled_samples, compare, wallet_returns
from brain_micro_prospective import reserve, verify, evaluate_due
from brain_research import Net


def data():
    ts = 100000 + np.arange(90)*5000
    return dict(ts=ts, symbols=np.repeat("SOLUSDT", len(ts)),
                sessions=np.repeat("session-a", len(ts)),
                x=np.zeros((len(ts), 8)), depth=np.repeat(100., len(ts)),
                ask=np.repeat(100., len(ts)), bid=np.repeat(100.1, len(ts)))


class ValidationTests(unittest.TestCase):
    def test_labels_charge_costs_and_delay(self):
        d = data()
        x,y,ts = labelled_samples(d, .0006, .0003)
        self.assertGreater(len(y), 0)
        self.assertAlmostEqual(y[0], -.0008, places=6)

    def test_no_labels_across_reconnect(self):
        d = data()
        d["sessions"] = np.array(["s"+str(i//20) for i in range(len(d["ts"]))])
        self.assertEqual(len(labelled_samples(d, 0, 0)[1]), 0)

    def test_missing_samples_cannot_bridge(self):
        d = data()
        keep = np.arange(len(d["ts"])) % 20 != 10
        d = {k:v[keep] for k,v in d.items()}
        self.assertEqual(len(labelled_samples(d, 0, 0)[1]), 0)

    def test_funding_boundary_excluded(self):
        d=data()
        d["ts"] = 3600000-60000+np.arange(30)*5000
        d={k:v[:30] for k,v in d.items()}
        self.assertEqual(len(labelled_samples(d, 0, 0)[1]), 0)

    def test_wallet_does_not_sum_overlapping_signals(self):
        ts=np.arange(100)*5000
        pnl=wallet_returns(np.ones(100), np.repeat(.01,100),ts,.001)
        self.assertEqual(np.count_nonzero(pnl),4)

    def test_losing_model_rejected_against_cash(self):
        d=data()
        r=compare(np.ones(90),d["x"],np.repeat(-.002,90),d["ts"])
        self.assertFalse(r["development_pass"])
        self.assertLess(r["controls"]["candidate"]["net_return"],0)

    def test_stale_delta_invalidates_book(self):
        s=Sampler()
        def row(kind,received,event,u):
            return dict(session="s",received_ms=received,message=dict(
                topic="orderbook.50.SOLUSDT",type=kind,ts=event,
                data=dict(u=u,seq=u,b=[["100","2"]],a=[["101","2"]])))
        s.ingest(row("snapshot",1000,1000,1))
        s.ingest(row("delta",5000,2000,2))
        s.ingest(row("delta",6000,6000,3))
        self.assertFalse(s.books)

    def test_stale_trade_does_not_enter_flow(self):
        s=Sampler()
        s.ingest(dict(session="a",received_ms=5000,message=dict(
            topic="publicTrade.SOLUSDT",data=[dict(T=1000,v="10",S="Buy"),
                                            dict(T=4999,v="2",S="Sell")])))
        self.assertEqual(list(s.flows["SOLUSDT"]),[(5000,-2.)])

    def test_prospective_freeze_and_tamper_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            d=pathlib.Path(td)
            model=d/"m.pt";scale=d/"s.npz"
            torch.save(Net().state_dict(),model)
            np.savez(scale,mean=np.zeros(8),std=np.ones(8))
            self.assertIsNone(reserve(d,model,scale,{"development_pass":False},1000))
            trial=pathlib.Path(reserve(d,model,scale,{"development_pass":True},1000))
            protocol=verify(trial)
            self.assertGreater(protocol["future_start_ms"],1000)
            self.assertIsNone(reserve(d,model,scale,{"development_pass":True},2000))
            evaluate_due(d,data(),2000)
            self.assertFalse((trial/"result.json").exists())
            (trial/"model.pt").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError,"artifact"):
                verify(trial)

if __name__=="__main__":
    unittest.main()
