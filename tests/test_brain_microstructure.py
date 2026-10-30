import unittest
from brain_microstructure import Sampler
class MicrostructureTests(unittest.TestCase):
    def row(self,kind="snapshot",seq=1,received=1000,event=990,bids=None,session="a"):
        return dict(session=session,received_ms=received,message=dict(topic="orderbook.50.BTCUSDT",
            type=kind,ts=event,data=dict(seq=seq,u=seq,b=bids if bids is not None else [["100","2"]],a=[["101","3"]])))
    def test_snapshot_delta_delete(self):
        s=Sampler();s.ingest(self.row());s.ingest(self.row("delta",2,bids=[["100","0"],["99","2"]]))
        self.assertNotIn(100,s.books["BTCUSDT"]["b"]);self.assertIn(99,s.books["BTCUSDT"]["b"])
    def test_out_of_order_invalidates(self):
        s=Sampler();s.ingest(self.row(seq=8));s.ingest(self.row("delta",7))
        self.assertNotIn("BTCUSDT",s.books)
    def test_reconnect_delta_without_snapshot_ignored(self):
        s=Sampler();s.ingest(self.row());s.ingest(self.row("delta",2,session="b"))
        self.assertFalse(s.books)
    def test_future_timestamp_ignored(self):
        s=Sampler();s.ingest(self.row(event=1100));self.assertFalse(s.books)
    def test_new_snapshot_discards_old_levels(self):
        s=Sampler();s.ingest(self.row());s.ingest(self.row(seq=3,bids=[["99","2"]]))
        self.assertNotIn(100,s.books["BTCUSDT"]["b"])
    def test_warmup_cannot_generate_signal(self):
        s=Sampler();self.assertIsNone(s.ingest(self.row()))
if __name__=="__main__":unittest.main()
