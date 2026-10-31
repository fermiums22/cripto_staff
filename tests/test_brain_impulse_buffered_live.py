from types import SimpleNamespace
import unittest
from brain_impulse_buffered_live import quote_for_execution
from brain_impulse_execution import initial_state,decide,on_book
from test_brain_impulse_execution import signal,INST


def fixture(received):
    raw=dict(session='s',received_ms=received,received_monotonic_ns=1000000000,receive_sequence=7,
        message=dict(topic='orderbook.50.SOLUSDT',ts=received-100))
    sampler=SimpleNamespace(books={'SOLUSDT':dict(received_ms=received,b={99.9:10},a={100.:10})})
    return raw,sampler


class BufferedLiveTests(unittest.TestCase):
    def test_actual_processing_clock_preserves_original_receipt(self):
        raw,sampler=fixture(100000)
        quote=quote_for_execution(raw,sampler,100200,1200000000)
        self.assertEqual(quote['ts'],100200);self.assertEqual(quote['source_received_ms'],100000)
        self.assertEqual(quote['event_ms'],99900);self.assertEqual(quote['processing_delay_ms'],200)
        self.assertIsNone(quote_for_execution(raw,sampler,104500,5500000000))

    def test_pre_latency_received_quote_cannot_be_used_as_later_fill(self):
        state=initial_state();decide(state,[signal()],100000)
        raw,sampler=fixture(100900)
        self.assertIsNone(quote_for_execution(raw,sampler,101100,1200000000,state['pending']))
        raw,sampler=fixture(101100)
        quote=quote_for_execution(raw,sampler,101200,1100000000,state['pending'])
        on_book(state,quote,INST)
        self.assertEqual(state['position']['opened_ms'],101200)
        self.assertEqual(state['position']['entry_delay_ms'],1200)

    def test_old_snapshot_or_invalidated_book_not_executed(self):
        raw,sampler=fixture(100000);sampler.books['SOLUSDT']['received_ms']=99999
        self.assertIsNone(quote_for_execution(raw,sampler,100100,1100000000))
        sampler.books.clear();self.assertIsNone(quote_for_execution(raw,sampler,100100,1100000000))


if __name__=='__main__':unittest.main()
