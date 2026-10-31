import json
import queue
import threading
import unittest
from brain_impulse_transport import BufferedReceiver,TransportFault,fresh_for_decision


class Socket:
    def __init__(self):self.q=queue.Queue();self.sent=[]
    def recv(self):
        try:return self.q.get(timeout=.05)
        except queue.Empty:raise TimeoutError()
    def send(self,value):self.sent.append(value)
    def close(self):self.q.put('')
    def put(self,n):self.q.put(json.dumps(dict(topic='orderbook.50.SOLUSDT',ts=1000,n=n)))


class TransportTests(unittest.TestCase):
    def test_receiver_drains_while_consumer_is_blocked_preserving_stamps(self):
        socket=Socket();receiver=BufferedReceiver(socket,'test',wall_ms=lambda:1100,monotonic_ns=lambda:1000000000).start()
        try:
            for n in range(100):socket.put(n)
            # Wait for ingestion without consuming: simulate a blocked ledger writer.
            with receiver.condition:
                self.assertTrue(receiver.condition.wait_for(lambda:receiver.received==100,timeout=2))
            self.assertEqual(receiver.metrics()['queued'],100)
            rows=[receiver.get() for _ in range(100)]
            self.assertEqual([r['message']['n'] for r in rows],list(range(100)))
            self.assertEqual(rows[0]['received_ms'],1100)
            self.assertTrue(fresh_for_decision(rows[0],1200,1100000000))
            self.assertFalse(fresh_for_decision(rows[0],5600,5500000000))
            self.assertFalse(fresh_for_decision(rows[0],1200,5500000000))
        finally:receiver.close()

    def test_overflow_invalidates_connection_not_just_one_delta(self):
        socket=Socket();receiver=BufferedReceiver(socket,'test',max_messages=2).start()
        try:
            for n in range(3):socket.put(n)
            with receiver.condition:self.assertTrue(receiver.condition.wait_for(lambda:receiver.error is not None,timeout=2))
            with self.assertRaisesRegex(TransportFault,'overflow'):receiver.get()
            self.assertEqual(receiver.metrics()['queued'],2)
        finally:receiver.close()

    def test_oversized_message_and_clock_regression_fail(self):
        socket=Socket();receiver=BufferedReceiver(socket,'test',max_bytes=5).start()
        try:
            socket.put(0)
            with self.assertRaisesRegex(TransportFault,'oversized'):receiver.get()
        finally:receiver.close()
        socket=Socket();clock=iter([1000,999]);receiver=BufferedReceiver(socket,'test',wall_ms=lambda:next(clock)).start()
        try:
            socket.put(0);socket.put(1)
            with receiver.condition:self.assertTrue(receiver.condition.wait_for(lambda:receiver.error is not None,timeout=2))
            with self.assertRaisesRegex(TransportFault,'clock_regression'):receiver.get()
        finally:receiver.close()


if __name__=='__main__':unittest.main()
