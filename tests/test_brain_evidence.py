import json, pathlib, tempfile, unittest
from unittest.mock import patch
import numpy as np
import brain_research as r
import brain_forward as f

def bars(n=100):
    a=np.zeros((n,6,6));rng=np.random.default_rng(13)
    a[:,:,0]=np.arange(n)[:,None]*r.STEP
    a[:,:,1]=100*np.exp(np.cumsum(rng.normal(0,.001,(n,6)),axis=0))
    a[:,:,4]=a[:,:,1]*1.001;a[:,:,2]=a[:,:,4]*1.01;a[:,:,3]=a[:,:,1]*.99
    a[:,:,5]=100
    return a

class EvidenceTests(unittest.TestCase):
    def test_future_cannot_change_features(self):
        a=bars();x=r.features(a)
        a[80:, :,1:5]*=10;a[80:,:,5]*=100
        np.testing.assert_array_equal(x[:80],r.features(a)[:80])
    def test_scaler_train_only(self):
        x=r.features(bars());m,s=r.fit_scaler(x[:50]);x[50:]*=1000
        m2,s2=r.fit_scaler(x[:50]);np.testing.assert_array_equal(m,m2);np.testing.assert_array_equal(s,s2)
    def test_depth_weighted_fill(self):
        self.assertAlmostEqual(f.fill([[100,1],[102,2]],2),101)
    def test_partial_fill_rejected(self):
        with self.assertRaises(ValueError):f.fill([[100,1]],2)
    def test_minimum_and_lot(self):
        inst={"lotSizeFilter":{"qtyStep":".1","minOrderQty":".1","minNotionalValue":"5","maxOrderQty":"100"}}
        self.assertEqual(f.quantity(12,10,inst),1.2)
        with self.assertRaises(ValueError):f.quantity(4,10,inst)
    def test_no_private_api(self):
        with patch.object(f,"api") as api:
            with self.assertRaises(ValueError):f.public("order/create")
            api.assert_not_called()
    def test_quote_latency_rejected(self):
        with patch.object(f,"now_ms",side_effect=[0,2000]),patch.object(f,"api",return_value={"time":2000}):
            with self.assertRaises(ValueError):f.public("tickers")
    def test_crossed_book_rejected(self):
        b={"result":{"ts":100,"b":[["101","1"]],"a":[["100","1"]]}}
        with patch.object(f,"public",return_value=(b,0,100)):
            with self.assertRaises(ValueError):f.book("BTCUSDT")
    def test_zero_strategy_no_fees(self):
        a=bars();meta={s:{"funding":[]} for s in r.SYMBOLS}
        pnl,active=r.pnl_series(np.zeros((98,6)),a,a[:,0,0],meta,1)
        self.assertEqual(pnl.sum(),0);self.assertEqual(active.sum(),0)
    def test_signal_cannot_fill_at_signal_close(self):
        a=bars();p=np.zeros((98,6));p[:,0]=.1
        meta={s:{"funding":[]} for s in r.SYMBOLS}
        pnl,_=r.pnl_series(p,a,a[:,0,0],meta,.01,0)
        np.testing.assert_allclose(pnl,a[2:,0,1]/a[1:-1,0,1]-1)
    def test_closed_trade_accounts_both_fees(self):
        w={"cash":15.-.006,"position":dict(symbol="X",qty=1.,entry=10.,side=1,
              entry_fee=.006,opened_ms=1,max_mark=10.),"trades":[]}
        b=dict(bids=[[11,10]],asks=[[12,10]],received_ms=2000,rtt_ms=100)
        with patch.object(f,"funding_cost",return_value=.02):f.close_position(w,b,"time")
        self.assertAlmostEqual(w["cash"]-15,w["trades"][0]["net_pnl"])
        self.assertIsNone(w["position"])
    def test_missing_control_matches_existing_unpaused_default(self):
        with patch("sqlite3.connect") as c:
            c.return_value.__enter__.return_value.execute.return_value.fetchone.return_value=None
            self.assertFalse(f.paused())
    def test_pause_fails_closed(self):
        with patch("sqlite3.connect",side_effect=OSError):self.assertTrue(f.paused())
    def test_atomic_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/"state.json";r.write(p,{"value":17})
            self.assertEqual(json.loads(p.read_text()),{"value":17})
            self.assertFalse(p.with_suffix(".json.tmp").exists())
    def test_no_readiness_without_trades(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/"p.json";r.write(p,{})
            result=f.evaluate(f.initial(p),{"future_start_ms":0})
            self.assertFalse(result["statistical_pass"]);self.assertFalse(result["ready"])
    def test_protocol_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);r.write(p/"protocol.json",{"artifact_hashes":{},"source_code_sha256":{}})
            r.write(p/"frozen.json",{"protocol_sha256":r.digest(p/"protocol.json")})
            f.verify(p);r.write(p/"protocol.json",{})
            with self.assertRaises(ValueError):f.verify(p)
if __name__=="__main__":unittest.main()
