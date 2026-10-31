"""Bounded timestamped socket ingestion, independent of slow durable writes.

No wallet or strategy code. A queue fault invalidates the whole connection; it
never drops a delta and pretends the remaining orderbook is continuous. Consumers
may reconstruct stale history, but must check fresh_for_decision before acting.
"""
from collections import deque
import json
import threading
import time
import websocket


class TransportFault(RuntimeError):pass


def fresh_for_decision(row,wall_ms=None,monotonic_ns=None,max_age_ms=1500):
    wall_ms=time.time_ns()//1000000 if wall_ms is None else wall_ms
    monotonic_ns=time.monotonic_ns() if monotonic_ns is None else monotonic_ns
    receipt=row['received_ms'];event=int(row['message'].get('ts',receipt))
    return (0<=wall_ms-receipt<=max_age_ms and 0<=wall_ms-event<=max_age_ms
            and 0<=(monotonic_ns-row['received_monotonic_ns'])/1000000<=max_age_ms)


class BufferedReceiver:
    def __init__(self,socket,session,max_messages=10000,max_bytes=8*1024*1024,
                 wall_ms=None,monotonic_ns=None):
        if min(max_messages,max_bytes)<=0:raise ValueError('Invalid buffer limit')
        self.socket=socket;self.session=session;self.max_messages=max_messages;self.max_bytes=max_bytes
        self.wall_ms=wall_ms or (lambda:time.time_ns()//1000000)
        self.monotonic_ns=monotonic_ns or time.monotonic_ns
        self.condition=threading.Condition();self.buffer=deque();self.bytes=0
        self.error=None;self.closed=False;self.received=0;self.peak_messages=0;self.peak_bytes=0
        self.thread=None

    def start(self):
        if self.thread is not None:raise RuntimeError('Receiver already started')
        self.thread=threading.Thread(target=self._read,name='impulse-public-receiver',daemon=True)
        self.thread.start();return self

    def _read(self):
        previous_wall=-1;previous_mono=-1;ping=time.monotonic()
        try:
            while not self.closed:
                if time.monotonic()-ping>=20:
                    self.socket.send(json.dumps(dict(op='ping')));ping=time.monotonic()
                try:raw=self.socket.recv()
                except (TimeoutError,websocket.WebSocketTimeoutException):continue
                wall=self.wall_ms();mono=self.monotonic_ns()
                if self.closed:return
                if not raw:raise TransportFault('socket_closed')
                if wall<previous_wall or mono<previous_mono:raise TransportFault('receipt_clock_regression')
                previous_wall,previous_mono=wall,mono
                size=len(raw.encode('utf-8')) if isinstance(raw,str) else len(raw)
                if size>self.max_bytes:raise TransportFault('oversized_message')
                message=json.loads(raw)
                if not isinstance(message,dict):raise TransportFault('invalid_message')
                if message.get('success') is False:raise TransportFault('subscription_rejected')
                with self.condition:
                    if len(self.buffer)>=self.max_messages or self.bytes+size>self.max_bytes:
                        raise TransportFault('receive_buffer_overflow')
                    self.received+=1
                    row=dict(session=self.session,received_ms=wall,received_monotonic_ns=mono,
                             receive_sequence=self.received,message=message)
                    self.buffer.append((row,size));self.bytes+=size
                    self.peak_messages=max(self.peak_messages,len(self.buffer));self.peak_bytes=max(self.peak_bytes,self.bytes)
                    self.condition.notify_all()
        except Exception as exc:
            with self.condition:
                if not self.closed:self.error=exc if isinstance(exc,TransportFault) else TransportFault(type(exc).__name__)
                self.condition.notify_all()
        finally:
            with self.condition:self.condition.notify_all()

    def get(self,timeout=1.):
        deadline=time.monotonic()+timeout
        with self.condition:
            while True:
                if self.error is not None:raise self.error
                if self.closed:raise TransportFault('receiver_closed')
                if self.buffer:
                    row,size=self.buffer.popleft();self.bytes-=size;return row
                left=deadline-time.monotonic()
                if left<=0:raise TimeoutError('No public message before deadline')
                self.condition.wait(left)

    def metrics(self):
        with self.condition:
            return dict(received=self.received,queued=len(self.buffer),queued_bytes=self.bytes,
                peak_messages=self.peak_messages,peak_bytes=self.peak_bytes,
                fault=str(self.error) if self.error else None,ready=False)

    def close(self):
        with self.condition:self.closed=True;self.condition.notify_all()
        self.socket.close()
        if self.thread is not None:
            self.thread.join(timeout=6)
            if self.thread.is_alive():raise TransportFault('socket_thread_did_not_stop')
