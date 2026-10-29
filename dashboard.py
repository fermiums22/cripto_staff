"""Private LAN dashboard. Only explicit public-to-this-dashboard fields are served."""
import argparse
import io
import json
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import agent


def snapshot(symbol='BTCUSDT', hours=24):
    if symbol not in agent.SYMBOLS or not 1 <= hours <= 168:
        raise ValueError('Invalid chart request')
    db = sqlite3.connect('file:'+str(agent.DATA/'agent.sqlite3')+'?mode=ro', uri=True, timeout=10)
    try:
        status_row = db.execute("SELECT value FROM state WHERE key='status'").fetchone()
        status = json.loads(status_row[0]) if status_row else {}
        control = db.execute("SELECT value FROM state WHERE key='control'").fetchone()
        status['paused'] = json.loads(control[0]).get('paused', False) if control else False
        since = int(time.time()*1000)-hours*3600000
        candles = db.execute('SELECT ts,open,high,low,close,volume FROM bars WHERE symbol=? AND ts>=? ORDER BY ts',
                             (symbol, since)).fetchall()
        signal = db.execute('SELECT ts,probability FROM signals WHERE symbol=? AND ts>=? ORDER BY ts',
                            (symbol, since)).fetchall()
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        equity = db.execute('SELECT ts,value FROM equity WHERE ts>=? ORDER BY ts', (since,)).fetchall() if 'equity' in tables else []
        events = [{'ts': t, 'kind': k, **json.loads(p)} for t, k, p in db.execute(
            'SELECT ts,kind,payload FROM events ORDER BY id DESC LIMIT 100')]
        counts = dict(db.execute('SELECT symbol,count(*) FROM bars GROUP BY symbol'))
        models_path = agent.ARTIFACTS/'models.json'
        models = json.loads(models_path.read_text()) if models_path.exists() else {}
        comparison_path = agent.ARTIFACTS/'comparison.json'
        comparison = json.loads(comparison_path.read_text(encoding='utf-8')) if comparison_path.exists() else None
        return dict(now_ms=int(time.time()*1000), status=status, symbol=symbol, candles=candles,
                    equity=equity, signals=signal, events=events, counts=counts, comparison=comparison,
                    models={s: {k: m.get(k) for k in ('id', 'samples', 'training_device', 'trained_through_ms')}
                            for s, m in models.items()})
    finally:
        db.close()


def graph_png():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import datetime
    data = snapshot()
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), layout='constrained')
    dates = lambda points: [datetime.datetime.fromtimestamp(p[0]/1000, datetime.timezone.utc) for p in points]
    candles = data['candles']
    axes[0].plot(dates(candles), [b[4] for b in candles], color='#008f85')
    axes[0].set_title('BTCUSDT | real Bybit spot, 5 min | UTC')
    equity = data['equity']
    if equity:
        axes[1].plot(dates(equity), [p[1] for p in equity], color='#437df5', marker='.' if len(equity)==1 else None)
    axes[1].axhline(15, color='gray', linestyle='--', linewidth=0.8)
    axes[1].set_title('Live PAPER equity (USDT) | not real money')
    for ax in axes:
        ax.grid(alpha=0.2)
    output = io.BytesIO()
    fig.savefig(output, format='png', dpi=140)
    plt.close(fig)
    return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == '/api/snapshot':
                query = parse_qs(parsed.query)
                content = json.dumps(snapshot(query.get('symbol', ['BTCUSDT'])[0],
                                              int(query.get('hours', ['24'])[0])), ensure_ascii=False).encode()
                kind = 'application/json; charset=utf-8'
            elif parsed.path in ('/', '/app.js', '/style.css'):
                name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[parsed.path]
                content = (agent.ROOT/'web'/name).read_bytes()
                kind = {'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8',
                        'style.css': 'text/css; charset=utf-8'}[name]
            else:
                self.send_error(404)
                return
        except (ValueError, KeyError):
            self.send_error(400)
            return
        except Exception:
            self.send_error(503, 'Dashboard data temporarily unavailable')
            return
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
