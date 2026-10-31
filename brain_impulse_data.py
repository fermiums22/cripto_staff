"""Versioned receive-time impulse features and executable depth labels.

Offline research only. No exchange client, credential access or wallet writes.
Ticker deltas merge into snapshots; liquidation side is POSITION side (Bybit).
Books use public depth only; RPI/hidden liquidity is never invented.
"""
import argparse
from collections import defaultdict, deque
from decimal import Decimal, ROUND_DOWN
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import time

import numpy as np

FEATURES = ('return_5s', 'return_15s', 'return_30s', 'return_60s',
            'acceleration_5s', 'volatility_30s', 'volatility_acceleration',
            'imbalance', 'imbalance_change_5s', 'log_bid_depth', 'log_ask_depth',
            'depth_change_5s', 'spread', 'flow_5s', 'flow_30s',
            'volume_acceleration', 'log_volume_30s', 'btc_5s', 'btc_30s',
            'eth_5s', 'eth_30s', 'btc_lead_residual', 'eth_lead_residual',
            'oi_change_30s', 'oi_known', 'funding', 'funding_known',
            'liquidated_longs_log_30s', 'liquidated_shorts_log_30s',
            'receipt_delay_ms')
HORIZONS = (10000, 30000, 60000, 120000)


def atomic_json(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w') as f:
        json.dump(value, f, allow_nan=False, sort_keys=True, indent=2)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


class ImpulseSampler:
    def __init__(self):
        self.session = None
        self.books = {}
        self.history = defaultdict(deque)
        self.trades = defaultdict(deque)
        self.liquidations = defaultdict(deque)
        self.tickers = {}
        self.oi = defaultdict(deque)
        self.last = {}
        self.last_received = -1
        self.clock_invalid = False
        self.audit = defaultdict(int)

    @staticmethod
    def trim(q, now, age=65000):
        while q and q[0][0] < now-age:
            q.popleft()

    def invalidate(self, symbol):
        self.books.pop(symbol, None)
        self.history.pop(symbol, None)
        self.audit['invalidated_books'] += 1

    def ingest(self, row):
        session = row.get('session')
        if session != self.session:
            self.__init__(); self.session = session
        now = int(row['received_ms'])
        if now < self.last_received:
            self.clock_invalid = True
        self.last_received = max(now, self.last_received)
        if self.clock_invalid:
            self.audit['clock_regression'] += 1
            return None  # A new session is required after a local clock regression.
        m = row.get('message', {})
        topic = m.get('topic', '')
        if not topic:
            return None
        symbol = topic.split('.')[-1]
        event = int(m.get('ts', now))
        if not 0 <= now-event <= 1500:
            self.audit['stale_or_future_messages'] += 1
            if topic.startswith('orderbook.'):
                self.invalidate(symbol)
            if topic.startswith('tickers.'):
                self.tickers.pop(symbol, None); self.oi.pop(symbol, None)
            return None
        if topic.startswith('tickers.'):
            d = m['data']
            if m.get('type') == 'snapshot':
                self.tickers[symbol] = {}
            if symbol not in self.tickers:
                return None
            t = self.tickers[symbol]
            t.update(d); t['_received'] = now
            if 'openInterest' in t:
                value = float(t['openInterest'])
                if math.isfinite(value) and value > 0:
                    if not self.oi[symbol] or now-self.oi[symbol][-1][0] >= 1000:
                        self.oi[symbol].append((now, value))
                    self.trim(self.oi[symbol], now)
            return None
        if topic.startswith(('publicTrade.', 'allLiquidation.')):
            liquidation = topic.startswith('allLiquidation.')
            q = self.liquidations[symbol] if liquidation else self.trades[symbol]
            for d in m['data']:
                value = float(d['v'])*float(d['p'])
                if (0 <= now-int(d['T']) <= 1500 and math.isfinite(value)
                        and value > 0 and d['S'] in ('Buy', 'Sell')):
                    q.append((now, value, d['S']))
            self.trim(q, now)
            return None
        if not topic.startswith('orderbook.'):
            return None
        d = m['data']
        reset = m.get('type') == 'snapshot' or d.get('u') == 1
        if reset:
            self.invalidate(symbol)
            self.books[symbol] = dict(b={}, a={}, seq=-1, u=-1)
        if symbol not in self.books:
            return None
        b = self.books[symbol]
        seq, update = int(d['seq']), int(d['u'])
        if not reset and (seq <= b['seq'] or update <= b['u']):
            self.invalidate(symbol)
            return None
        for side in ('b', 'a'):
            for price, qty in d.get(side, []):
                price, qty = float(price), float(qty)
                if not math.isfinite(price*qty) or price <= 0 or qty < 0:
                    self.invalidate(symbol); return None
                if qty == 0:
                    b[side].pop(price, None)
                else:
                    b[side][price] = qty
        b.update(seq=seq, u=update, received_ms=now)
        if not b['b'] or not b['a'] or max(b['b']) >= min(b['a']):
            self.invalidate(symbol); return None
        # Coarsen feature calculations to 1Hz, retaining every delta in the book.
        h = self.history[symbol]
        if h and now-h[-1][0] < 1000:
            return None
        bids = sorted(b['b'].items(), reverse=True)[:50]
        asks = sorted(b['a'].items())[:50]
        mid = (bids[0][0]+asks[0][0])/2
        bd = sum(p*q for p, q in bids[:10]); ad = sum(p*q for p, q in asks[:10])
        imbalance = (bd-ad)/(bd+ad)
        h.append((now, mid, imbalance, bd+ad)); self.trim(h, now)
        if now-self.last.get(symbol, 0) < 5000:
            return None
        def past(history, lag):
            v = next((v for v in reversed(history) if v[0] <= now-lag), None)
            return v if v is not None and now-lag-v[0] <= 1500 else None
        def ret(s, lag):
            history = self.history[s]
            if not history or not 0 <= now-history[-1][0] <= 1500:
                return None
            v = past(history, lag)
            return math.log(history[-1][1]/v[1]) if v else None
        returns = [ret(symbol, lag) for lag in (5000, 15000, 30000, 60000)]
        leads = [ret(s, lag) for s in ('BTCUSDT', 'ETHUSDT') for lag in (5000, 30000)]
        previous = past(h, 5000)
        if any(v is None for v in returns+leads) or previous is None:
            return None
        if any(y[0]-x[0] > 2500 for x, y in zip(h, list(h)[1:])):
            self.audit['history_gaps'] += 1
            return None
        r5, r15, r30, r60 = returns
        vals = [(y[0], math.log(y[1]/x[1])) for x, y in zip(h, list(h)[1:])]
        vol = lambda lo, hi: math.sqrt(sum(v*v for t, v in vals if now-hi < t <= now-lo))
        self.trim(self.trades[symbol], now)
        recent = [(t, v*(1 if side == 'Buy' else -1)) for t, v, side in self.trades[symbol] if now-t <= 30000]
        v5 = sum(abs(v) for t, v in recent if now-t <= 5000)
        v30 = sum(abs(v) for t, v in recent)
        f5 = sum(v for t, v in recent if now-t <= 5000)/(v5+1e-12)
        f30 = sum(v for t, v in recent)/(v30+1e-12)
        ticker = self.tickers.get(symbol, {})
        fresh = now-ticker.get('_received', -10**15) <= 1500
        old_oi = past(self.oi[symbol], 30000)
        oi_known = fresh and old_oi is not None and bool(self.oi[symbol])
        oi_change = math.log(self.oi[symbol][-1][1]/old_oi[1]) if oi_known else 0.
        funding_known = fresh and 'fundingRate' in ticker
        funding = float(ticker['fundingRate']) if funding_known else 0.
        self.trim(self.liquidations[symbol], now)
        liqs = [sum(v for t, v, side in self.liquidations[symbol] if now-t <= 30000 and side == s)
                for s in ('Buy', 'Sell')]
        x = [*returns, r5-(r15-r5)/2, vol(0, 30000), vol(0, 15000)-vol(15000, 30000),
             imbalance, imbalance-previous[2], math.log1p(bd), math.log1p(ad),
             math.log((bd+ad)/previous[3]), (asks[0][0]-bids[0][0])/mid,
             f5, f30, math.log1p(v5)-math.log1p((v30-v5)/5), math.log1p(v30),
             *leads, leads[0]-r5, leads[2]-r5, oi_change, float(oi_known), funding,
             float(funding_known), *[math.log1p(v) for v in liqs], now-event]
        if not all(math.isfinite(v) for v in x):
            return None
        self.last[symbol] = now
        return dict(session=self.session, symbol=symbol, ts=now, event_ms=event,
                    x=x, bids=bids, asks=asks)


def consume(levels, qty):
    """Total executable quote value; unavailable depth is a rejection."""
    remaining, value = qty, 0.
    for price, available in levels:
        take = min(remaining, available)
        value += take*price; remaining -= take
        if remaining <= max(1e-12, qty*1e-12):
            return value
    return None


def execution_label(entry, exit_row, lot, side, notional=12., fee=.0006, slip=.0003):
    if side not in (-1, 1):
        raise ValueError('side')
    levels = entry['asks'] if side == 1 else entry['bids']
    step = Decimal(lot['qtyStep'])
    budget_price = levels[0][0]*(1+slip)*(1+fee)
    qty = float((Decimal(str(notional))/Decimal(str(budget_price))/step)
                .to_integral_value(rounding=ROUND_DOWN)*step)
    if qty < float(lot['minOrderQty']) or qty <= 0:
        return None
    enter = consume(levels, qty)
    leave = consume(exit_row['bids'] if side == 1 else exit_row['asks'], qty)
    if enter is None or leave is None:
        return None
    enter *= 1+side*slip; leave *= 1-side*slip
    # Entry notional plus fees cannot exceed the research budget.
    if enter*(1+fee) > notional or enter < float(lot.get('minNotionalValue', 5)):
        return None
    fees = fee*(enter+leave)
    pnl = side*(leave-enter)-fees
    return dict(qty=qty, entry_notional=enter, exit_notional=leave, fees=fees,
                net_pnl=pnl, net_return=pnl/notional)


def labels(rows, instruments, horizons=HORIZONS):
    """Targets never bridge sessions/gaps or funding hours; sampled latency recorded."""
    groups = defaultdict(list)
    for row in rows:
        groups[(row['session'], row['symbol'])].append(row)
    output = []
    for (_, symbol), group in groups.items():
        group.sort(key=lambda r: r['ts'])
        ts = np.array([r['ts'] for r in group])
        lot = instruments[symbol]['lotSizeFilter']
        for i, row in enumerate(group):
            ei = int(np.searchsorted(ts, ts[i]+1000))
            if ei >= len(ts) or not 1000 <= ts[ei]-ts[i] <= 7000:
                continue
            for horizon in horizons:
                zi = int(np.searchsorted(ts, ts[ei]+horizon))
                if zi >= len(ts) or ts[zi]-ts[ei] > horizon+6000:
                    continue
                if ts[i]//3600000 != ts[zi]//3600000 or np.any(np.diff(ts[i:zi+1]) > 7000):
                    continue
                for side in (1, -1):
                    result = execution_label(group[ei], group[zi], lot, side)
                    if result is not None:
                        output.append(dict(symbol=symbol, session=row['session'], ts=row['ts'],
                            exit_ms=int(ts[zi]), latency_ms=int(ts[ei]-ts[i]), horizon_ms=horizon,
                            side=side, x=row['x'], **result))
    return output


def extract(source, output, max_files=12):
    """Incremental bounded extraction; append-only source-addressed artifacts."""
    output.mkdir(parents=True, exist_ok=True)
    version = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    destination = output/version[:16]; destination.mkdir(exist_ok=True)
    done = 0
    for path in sorted(source.glob('*/*.jsonl.gz')):
        if time.time()-path.stat().st_mtime < 310:
            continue
        manifest = destination/(path.name+'.json')
        if manifest.exists():
            continue
        sampler = ImpulseSampler(); rows = []; count = 0
        try:
            with gzip.open(path, 'rt') as f:
                for line in f:
                    row = sampler.ingest(json.loads(line)); count += 1
                    if row is not None:
                        rows.append(row)
        except (EOFError, OSError, ValueError, KeyError) as exc:
            atomic_json(destination/(path.name+'.error.json'), dict(error=str(exc), ready=False))
            continue
        target = destination/(path.name+'.samples.jsonl.gz')
        tmp = target.with_suffix('.tmp')
        with gzip.open(tmp, 'wt', compresslevel=3) as f:
            for row in rows:
                f.write(json.dumps(row, allow_nan=False, separators=(',', ':'))+'\n')
        with tmp.open('rb') as f:
            os.fsync(f.fileno())
        os.replace(tmp, target)
        atomic_json(manifest, dict(source=str(path), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            code_sha256=version, features=FEATURES, messages=count, samples=len(rows),
            first_ms=rows[0]['ts'] if rows else None, last_ms=rows[-1]['ts'] if rows else None,
            audit=dict(sampler.audit), ready=False))
        done += 1
        if done >= max_files:
            break
    manifests = [json.loads(p.read_text()) for p in destination.glob('*.json') if not p.name.endswith('.error.json')]
    atomic_json(output/'status.json', dict(updated_ms=int(time.time()*1000), code_sha256=version,
        completed_files=len(manifests), samples=sum(m['samples'] for m in manifests),
        new_files=done, ready=False, mode='Feature audit only; no fitted model or promotion',
        limitations=['5s sampled execution, not tick-accurate execution', 'No maker queue simulation',
                     'Funding-crossing labels excluded', 'Current lot rules are not historical point-in-time rules']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-files', type=int, default=12)
    args = parser.parse_args()
    extract(args.source, args.output, args.max_files)
