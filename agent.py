"""Public Bybit data, reproducible baseline research and local spot paper trading."""
import argparse
import json
import logging
import math
import sqlite3
import statistics
import time
import urllib.parse
import urllib.request
from decimal import Decimal, ROUND_DOWN
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
ARTIFACTS = ROOT / 'artifacts'
SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
BAR_MS = 300_000
HORIZON = 12
FEE = 0.001  # Explicit simulation assumption; not an account-specific fee quote.
SLIP = 0.0005  # Applied per side in addition to the observed live spread.
THRESHOLD = 0.60
TP = 0.015
SL = 0.01


def api(endpoint, **params):
    # No credentials, private endpoints, proxy inheritance or order API exists here.
    url = 'https://api.bybit.com/v5/market/' + endpoint + '?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={'User-Agent': 'cripto-staff-paper/0.1'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(3):
        try:
            with opener.open(request, timeout=20) as response:
                result = json.load(response)
            if result.get('retCode') != 0:
                raise RuntimeError('Bybit: ' + str(result.get('retMsg')))
            return result
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def connect():
    DATA.mkdir(exist_ok=True)
    db = sqlite3.connect(DATA / 'agent.sqlite3', timeout=10)
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
      CREATE TABLE IF NOT EXISTS bars (
        symbol TEXT, ts INTEGER, open REAL, high REAL, low REAL, close REAL,
        volume REAL, PRIMARY KEY(symbol,ts));
      CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
      CREATE TABLE IF NOT EXISTS signals (
        symbol TEXT, ts INTEGER, probability REAL, model_id TEXT,
        PRIMARY KEY(symbol,ts));
      CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY, ts INTEGER, kind TEXT, payload TEXT);
      CREATE TABLE IF NOT EXISTS equity (
        ts INTEGER PRIMARY KEY, value REAL, cash REAL, symbol TEXT);
    ''')
    with db:
        db.execute("INSERT OR IGNORE INTO state VALUES ('portfolio', ?)",
                   (json.dumps({'cash': 15.0, 'position': None}),))
    return db


def closed_bars(rows, server_ms):
    bars = []
    for row in rows:
        ts = int(row[0])
        values = list(map(float, row[1:6]))
        if ts + BAR_MS > server_ms:
            continue
        o, h, low, close, volume = values
        if (ts % BAR_MS or not all(math.isfinite(v) for v in values)
                or min(o, h, low, close) <= 0 or volume < 0
                or low > min(o, close) or h < max(o, close) or low > h):
            raise ValueError('Invalid candle')
        bars.append([ts, *values])
    return sorted(bars)


def collect(db, symbol, days=30):
    latest = db.execute('SELECT MAX(ts) FROM bars WHERE symbol=?', (symbol,)).fetchone()[0]
    cutoff = latest if latest is not None else int(time.time() * 1000) - days * 86400000
    end = None
    count = 0
    while True:
        args = dict(category='spot', symbol=symbol, interval='5', limit=1000)
        if end is not None:
            args['end'] = end
        result = api('kline', **args)
        rows = result['result']['list']
        if not rows:
            break
        bars = [b for b in closed_bars(rows, int(result['time'])) if b[0] >= cutoff]
        with db:
            db.executemany('INSERT OR IGNORE INTO bars VALUES (?,?,?,?,?,?,?)',
                           [(symbol, *b) for b in bars])
        count += len(bars)
        oldest = min(int(r[0]) for r in rows)
        if oldest <= cutoff:
            break
        if end is not None and oldest >= end:
            raise RuntimeError('Pagination did not advance')
        end = oldest - 1
        time.sleep(0.15)
    return count


def read_bars(db, symbol):
    return db.execute('SELECT ts,open,high,low,close,volume FROM bars WHERE symbol=? ORDER BY ts',
                      (symbol,)).fetchall()


def features(bars, i):
    if i < 24 or any(bars[k][0] - bars[k-1][0] != BAR_MS for k in range(i-23, i+1)):
        return None
    close = bars[i][4]
    returns = [close / bars[i-lag][4] - 1 for lag in (1, 3, 6, 12, 24)]
    one = [bars[k][4] / bars[k-1][4] - 1 for k in range(i-23, i+1)]
    average_volume = statistics.mean(b[5] for b in bars[i-23:i+1])
    return returns + [statistics.pstdev(one), (bars[i][2] - bars[i][3]) / close,
                      bars[i][5] / average_volume - 1 if average_volume else 0]


@lru_cache(maxsize=4)
def predictor(raw):
    import xgboost as xgb
    booster = xgb.Booster()
    booster.load_model(bytearray(raw, 'utf-8'))
    booster.set_param({'device': 'cpu', 'nthread': 2})
    return booster


def probabilities(model, xs):
    import numpy as np
    return predictor(model['raw']).inplace_predict(np.asarray(xs, dtype=np.float32)).tolist()


def probability(model, x):
    return probabilities(model, [x])[0]


def exit_price(bar, entry, age):
    # If both TP/SL appear in one bar, assume the adverse ordering.
    stop, take = entry * (1-SL), entry * (1+TP)
    if bar[1] <= stop:
        return bar[1], 'gap_stop'
    if bar[3] <= stop:
        return stop, 'stop'
    if bar[2] >= take:
        return take, 'take'
    if age >= HORIZON:
        return bar[4], 'timeout'
    return None


def backtest(bars, predictions, start, end, trace=False):
    cash, position, trades, peak, drawdown = 15.0, None, 0, 15.0, 0.0
    curve, executions = [], []
    for i in range(start, end):
        bar = bars[i]
        if position is None and predictions.get(i-1, 0) >= THRESHOLD:
            entry = bar[1] * (1+SLIP)
            budget = cash * 0.9
            qty = budget / (entry * (1+FEE))
            cash -= budget
            position = (entry, qty, i)
            if trace:
                executions.append({'ts': bar[0], 'kind': 'entry', 'price': entry})
        if position:
            entry, qty, opened = position
            hit = exit_price(bar, entry, i-opened+1)
            if hit or i == end-1:
                price = (hit[0] if hit else bar[4]) * (1-SLIP)
                cash += qty * price * (1-FEE)
                if trace:
                    executions.append({'ts': bar[0]+BAR_MS, 'kind': 'exit', 'price': price,
                                       'reason': hit[1] if hit else 'end_of_test',
                                       'pnl': qty*(price*(1-FEE)-entry*(1+FEE))})
                position = None
                trades += 1
        equity = cash + (position[1] * bar[4] * (1-SLIP) * (1-FEE) if position else 0)
        peak = max(peak, equity)
        drawdown = max(drawdown, 1-equity/peak)
        if trace:
            curve.append([bar[0]+BAR_MS, equity])
    result = {'end_usdt': cash, 'return_pct': (cash/15-1)*100,
              'trades': trades, 'max_drawdown_pct': drawdown*100}
    if trace:
        result.update(curve=curve, executions=executions)
    return result


def fit_model(xs, ys):
    import numpy as np
    from xgboost import XGBClassifier
    estimator = XGBClassifier(device='cuda', tree_method='hist', n_estimators=150,
                              max_depth=3, learning_rate=0.04, subsample=0.8,
                              colsample_bytree=0.8, reg_lambda=10, n_jobs=2,
                              random_state=42, objective='binary:logistic')
    estimator.fit(np.asarray(xs, dtype=np.float32), np.asarray(ys))
    booster = estimator.get_booster()
    config = json.loads(booster.save_config())
    device = config['learner']['generic_param']['device']
    if not device.startswith('cuda'):
        raise RuntimeError('GPU training required; XGBoost fell back to ' + device)
    logging.info('Trained XGBoost on %s, samples=%s', device, len(xs))
    return {'raw': booster.save_raw(raw_format='json').decode('utf-8'),
            'training_device': device, 'algorithm': 'xgboost'}


def train(db):
    ARTIFACTS.mkdir(exist_ok=True)
    models, reports = {}, {}
    for symbol in SYMBOLS:
        bars = read_bars(db, symbol)
        if len(bars) < 2000:
            raise RuntimeError('Need at least 2000 closed candles per symbol')
        if any(bars[i][0] - bars[i-1][0] != BAR_MS for i in range(1, len(bars))):
            raise RuntimeError('History contains gaps: ' + symbol)
        xs, ys, indices = [], [], []
        for i in range(24, len(bars)-HORIZON):
            x = features(bars, i)
            entry = bars[i+1][1] * (1+SLIP) * (1+FEE)
            outcome = bars[i+HORIZON][4] * (1-SLIP) * (1-FEE) / entry - 1
            xs.append(x); ys.append(int(outcome > 0)); indices.append(i)
        folds = []
        for fraction in (0.5, 0.65, 0.8):
            start = int(len(bars)*fraction)
            end = min(len(bars), start+int(len(bars)*0.15))
            # Purge labels whose future horizon reaches the evaluation boundary.
            train_rows = [k for k, i in enumerate(indices) if i+HORIZON < start]
            model = fit_model([xs[k] for k in train_rows], [ys[k] for k in train_rows])
            evaluation = list(range(start, end-1))
            preds = dict(zip(evaluation, probabilities(model, [features(bars, i) for i in evaluation])))
            result = backtest(bars, preds, start+1, end)
            buy_hold = bars[end-1][4]*(1-SLIP)*(1-FEE)/(bars[start+1][1]*(1+SLIP)*(1+FEE))-1
            result.update(start_ms=bars[start][0], end_ms=bars[end-1][0],
                          train_samples=len(train_rows), buy_hold_pct=buy_hold*100,
                          cash_baseline_pct=0)
            folds.append(result)
        final = fit_model(xs, ys)
        final.update(symbol=symbol, trained_through_ms=bars[-1][0],
                     id=symbol+'-'+str(bars[-1][0]), samples=len(xs))
        models[symbol] = final
        reports[symbol] = {'candles': len(bars), 'folds': folds}
    report = {'created_ms': int(time.time()*1000), 'symbols': reports,
              'mode': 'experimental_spot_paper', 'fee_per_side': FEE,
              'slippage_per_side': SLIP,
              'limitations': ['No historical order book spread or minimum-order filters in backtests',
                              'No leverage, derivatives, funding or RL',
                              'Each backtest symbol has a separate $15 test account',
                              'No profitability or automatic strategy approval claim']}
    for name, value in [('models.json', models), ('research.json', report)]:
        tmp = ARTIFACTS / (name+'.tmp')
        tmp.write_text(json.dumps(value, indent=2), encoding='utf-8')
        tmp.replace(ARTIFACTS / name)
    return report


def order_quantity(cash, ask, lot):
    price = Decimal(str(ask)) * (1+Decimal(str(SLIP)))
    budget = Decimal(str(cash)) * Decimal('0.9')
    step = Decimal(lot['basePrecision'])
    qty = (budget / (price*(1+Decimal(str(FEE)))) / step).to_integral_value(rounding=ROUND_DOWN)*step
    if qty < Decimal(lot['minOrderQty']) or qty*price < Decimal(lot['minOrderAmt']):
        return 0.0
    maximum = lot.get('maxMarketOrderQty', lot.get('maxOrderQty'))
    if maximum and qty > Decimal(maximum):
        return 0.0
    return float(qty)


def event(db, now, kind, payload):
    db.execute('INSERT INTO events(ts,kind,payload) VALUES (?,?,?)',
               (now, kind, json.dumps(payload)))
    logging.info('%s %s', kind, json.dumps(payload))


def cycle(db, models, instruments):
    quotes, signals, newest, decisions = {}, [], {}, {}
    for symbol in SYMBOLS:
        collect(db, symbol)
        bars = read_bars(db, symbol)
        ticker = api('tickers', category='spot', symbol=symbol)
        q = ticker['result']['list'][0]
        now = int(ticker['time'])
        bid, ask = float(q['bid1Price']), float(q['ask1Price'])
        if not (0 < bid <= ask and math.isfinite(ask)):
            raise RuntimeError('Invalid quote')
        if abs(int(time.time()*1000)-now) > 60000:
            raise RuntimeError('Clock skew or stale quote')
        quotes[symbol] = (bid, ask, now)
        last = bars[-1]
        newest[symbol] = last[0]
        x = features(bars, len(bars)-1)
        prob = probability(models[symbol], x) if x is not None else None
        fresh = 0 <= now-(last[0]+BAR_MS) < 120000
        decisions[symbol] = dict(probability=prob, threshold=THRESHOLD,
                                 candle_ms=last[0], bid=bid, ask=ask,
                                 reason='data_gap' if x is None else 'stale_signal' if not fresh else
                                 'below_threshold' if prob < THRESHOLD else 'eligible')
        if x is not None and fresh:
            signals.append((symbol, last[0], prob, models[symbol]['id']))
    # All simulated accounting and the processed-signal watermark commit together.
    with db:
        db.execute('BEGIN IMMEDIATE')
        control = db.execute("SELECT value FROM state WHERE key='control'").fetchone()
        paused = json.loads(control[0]).get('paused', False) if control else False
        portfolio = json.loads(db.execute("SELECT value FROM state WHERE key='portfolio'").fetchone()[0])
        pos = portfolio['position']
        if pos:
            bid, _, now = quotes[pos['symbol']]
            reason = ('stop' if bid <= pos['entry']*(1-SL) else
                      'take' if bid >= pos['entry']*(1+TP) else
                      'timeout' if now-pos['opened_ms'] >= HORIZON*BAR_MS else None)
            if reason:
                proceeds = pos['qty']*bid*(1-SLIP)*(1-FEE)
                portfolio['cash'] += proceeds
                portfolio['position'] = None
                event(db, now, 'paper_exit', {**pos, 'reason': reason, 'proceeds': proceeds,
                                             'pnl_usdt': proceeds-pos['cost']})
        for symbol, ts, prob, model_id in sorted(signals, key=lambda s: s[2], reverse=True):
            inserted = db.execute('INSERT OR IGNORE INTO signals VALUES (?,?,?,?)',
                                  (symbol, ts, prob, model_id)).rowcount
            if paused:
                decisions[symbol]['reason'] = 'paused'
                continue
            if portfolio['position']:
                decisions[symbol]['reason'] = 'position_open'
                continue
            if not inserted or prob < THRESHOLD:
                if not inserted and prob >= THRESHOLD:
                    decisions[symbol]['reason'] = 'already_processed'
                continue
            _, ask, now = quotes[symbol]
            if int(time.time()*1000)-now > 15000:
                continue
            qty = order_quantity(portfolio['cash'], ask, instruments[symbol]['lotSizeFilter'])
            if qty <= 0:
                decisions[symbol]['reason'] = 'minimum_order'
                event(db, now, 'skip_minimum_order', {'symbol': symbol})
                continue
            entry = ask*(1+SLIP)
            cost = qty*entry*(1+FEE)
            portfolio['cash'] -= cost
            portfolio['position'] = dict(symbol=symbol, qty=qty, entry=entry, cost=cost,
                                         opened_ms=now, probability=prob, model_id=model_id)
            event(db, now, 'paper_entry', portfolio['position'])
            decisions[symbol]['reason'] = 'paper_entry'
        db.execute("UPDATE state SET value=? WHERE key='portfolio'", (json.dumps(portfolio),))
        pos = portfolio['position']
        equity = portfolio['cash'] + (pos['qty']*quotes[pos['symbol']][0]*(1-SLIP)*(1-FEE) if pos else 0)
        snapshot = dict(mode='experimental_spot_paper', heartbeat_ms=int(time.time()*1000),
                        equity_usdt=equity, pnl_usdt=equity-15, portfolio=portfolio,
                        latest_candles_ms=newest, signals=signals, last_error=None,
                        paused=paused, decisions=decisions)
        db.execute('INSERT OR REPLACE INTO equity VALUES (?,?,?,?)',
                   (snapshot['heartbeat_ms'], equity, portfolio['cash'], pos['symbol'] if pos else None))
        db.execute("INSERT OR REPLACE INTO state VALUES ('status',?)", (json.dumps(snapshot),))
    logging.info('heartbeat equity=%.6f position=%s signals=%s', equity,
                 pos['symbol'] if pos else 'none', [(s[0], round(s[2], 3)) for s in signals])


def run(db):
    models = json.loads((ARTIFACTS/'models.json').read_text())
    instruments, refreshed = {}, 0
    while True:
        try:
            if time.time()-refreshed > 3600:
                instruments = {s: api('instruments-info', category='spot', symbol=s)['result']['list'][0]
                               for s in SYMBOLS}
                if any(i['status'] != 'Trading' for i in instruments.values()):
                    raise RuntimeError('Instrument not trading')
                refreshed = time.time()
            cycle(db, models, instruments)
        except Exception as exc:
            logging.exception('cycle failed; no fabricated prices')
            with db:
                event(db, int(time.time()*1000), 'error', {'message': str(exc)})
                old = db.execute("SELECT value FROM state WHERE key='status'").fetchone()
                status = json.loads(old[0]) if old else {}
                status.update(last_error=str(exc), error_ms=int(time.time()*1000))
                db.execute("INSERT OR REPLACE INTO state VALUES ('status',?)", (json.dumps(status),))
        time.sleep(30)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['research', 'run', 'status'])
    args = parser.parse_args()
    with connect() as db:
        if args.command == 'research':
            for symbol in SYMBOLS:
                count = collect(db, symbol)
                logging.info('Collected %s %s bars', symbol, count)
            report = train(db)
            print(json.dumps(report, indent=2))
        elif args.command == 'run':
            run(db)
        else:
            row = db.execute("SELECT value FROM state WHERE key='status'").fetchone()
            print(json.dumps(json.loads(row[0]) if row else {'status': 'not_started'}, indent=2))


if __name__ == '__main__':
    main()
