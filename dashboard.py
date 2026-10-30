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
        arena=[];arena_status=None
        if 'arena_accounts' in tables:
            arena=[dict(id=key,**json.loads(payload)) for key,payload in db.execute('SELECT id,payload FROM arena_accounts ORDER BY id')]
            row=db.execute("SELECT value FROM state WHERE key='arena_status'").fetchone()
            arena_status=json.loads(row[0]) if row else None
            for account in arena:
                points=db.execute('SELECT ts,value FROM arena_equity WHERE strategy=? AND ts>=? ORDER BY ts', (account['id'],since)).fetchall()
                account['curve']=points[::max(1,len(points)//600)]+points[-1:]
        equity = db.execute('SELECT ts,value FROM equity WHERE ts>=? ORDER BY ts', (since,)).fetchall() if 'equity' in tables else []
        events = [{'ts': t, 'kind': k, **json.loads(p)} for t, k, p in db.execute(
            'SELECT ts,kind,payload FROM events ORDER BY id DESC LIMIT 100')]
        counts = dict(db.execute('SELECT symbol,count(*) FROM bars GROUP BY symbol'))
        models_path = agent.ARTIFACTS/'models.json'
        models = json.loads(models_path.read_text()) if models_path.exists() else {}
        comparison_path = agent.ARTIFACTS/'comparison.json'
        comparison = json.loads(comparison_path.read_text(encoding='utf-8')) if comparison_path.exists() else None
        extra = {}
        for key, filename in [('research_job','research_status.json'),('search_result','search_result.json'),('market_context','market_context.json'),('arena_backtest','arena_backtest.json'),('waiting_research','waiting_research.json'),('sourced_research','sourced_research.json'),('window_experiment','window_experiment.json'),('random_brackets','random_brackets.json'),('nested_windows','nested_windows.json'),('execution_research','execution_research.json'),('evolution_research','evolution_research.json'),('evolution_status','evolution_status.json'),('portfolio_research','portfolio_research.json'),('portfolio_audit','portfolio_audit.json'),('portfolio_status','portfolio_status.json'),('market_scan','market_scan.json'),('market_stream_status','market_stream_status.json')]:
            path=agent.ARTIFACTS/filename
            extra[key]=json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        return dict(now_ms=int(time.time()*1000), status=status, symbol=symbol, candles=candles,
                    equity=equity, signals=signal, events=events, counts=counts, comparison=comparison,
                    arena=arena,arena_status=arena_status,
                    models={s: {k: m.get(k) for k in ('id', 'samples', 'training_device', 'trained_through_ms')}
                            for s, m in models.items()}, **extra)
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
    if data.get('arena'):
        for account in data['arena']:
            points=account['curve']
            if points:axes[1].plot(dates(points),[p[1] for p in points],label=account['name'])
        axes[1].legend(fontsize=7,loc='best')
    elif equity:
        axes[1].plot(dates(equity), [p[1] for p in equity], color='#437df5', marker='.' if len(equity)==1 else None)
    axes[1].axhline(15, color='gray', linestyle='--', linewidth=0.8)
    axes[1].set_title('Live PAPER comparison (USDT) | independent $15 accounts')
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
            if parsed.path == '/api/adaptive':
                data = {}
                for key in ('research', 'live'):
                    path = agent.ARTIFACTS/('adaptive_'+key+'.json')
                    data[key] = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
                content = json.dumps(dict(now_ms=int(time.time()*1000), **data), ensure_ascii=False).encode()
                kind = 'application/json; charset=utf-8'
            elif parsed.path == '/api/snapshot':
                query = parse_qs(parsed.query)
                content = json.dumps(snapshot(query.get('symbol', ['BTCUSDT'])[0],
                                              int(query.get('hours', ['24'])[0])), ensure_ascii=False).encode()
                kind = 'application/json; charset=utf-8'
            elif parsed.path in ('/', '/app.js', '/style.css', '/adaptive', '/adaptive.js', '/adaptive.css'):
                name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css',
                        '/adaptive': 'adaptive.html', '/adaptive.js': 'adaptive.js', '/adaptive.css': 'adaptive.css'}[parsed.path]
                content = (agent.ROOT/'web'/name).read_bytes()
                kind = {'html': 'text/html; charset=utf-8', 'js': 'text/javascript; charset=utf-8',
                        'css': 'text/css; charset=utf-8'}[name.rsplit('.', 1)[1]]
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
