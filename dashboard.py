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
    import matplotlib.dates as mdates
    import datetime
    path = agent.ARTIFACTS/'adaptive_live.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    wallet = data.get('wallet', {})
    points = wallet.get('curve', [])
    fig, ax = plt.subplots(figsize=(10, 6))
    fig.subplots_adjust(top=.66, bottom=.17, left=.10, right=.97)
    dates = lambda points: [datetime.datetime.fromtimestamp(p[0]/1000, datetime.timezone.utc) for p in points]
    fig.suptitle('Адаптивный PAPER · '+data.get('selected', 'ожидание запуска'), fontsize=15, y=.96)
    if points:
        ax.plot(dates(points), [p[1] for p in points], color='#008f85', linewidth=2,
                marker='.' if len(points)==1 else None, label='Общий кошелёк · LIVE PAPER')
        values = [15., *[p[1] for p in points]]
        padding = max(.05, (max(values)-min(values))*.1)
        ax.set_ylim(min(values)-padding, max(values)+padding)
    else:
        ax.text(.5, .5, 'Ожидание живой истории кошелька', transform=ax.transAxes, ha='center')
    ax.axhline(15, color='gray', linestyle='--', linewidth=.8, label='Старт $15')
    ax.set_ylabel('USDT'); ax.set_xlabel('UTC'); ax.grid(alpha=.2); ax.legend(loc='best', fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m %H:%M', tz=datetime.timezone.utc))
    ax.tick_params(axis='x', labelsize=9)
    equity = data.get('equity', points[-1][1] if points else None)
    capital = f'${equity:.4f}' if equity is not None else 'нет данных'
    position = wallet.get('position')
    holding = f"{position['symbol']} {'LONG' if position['side']>0 else 'SHORT'}" if position else 'нет позиции'
    status = 'Входы разрешены' if data.get('live_gate') else 'Сбор данных · входы отключены: отбор убыточен'
    if not data:
        status = 'Ожидание данных адаптивного сервиса'
    if data.get('paused'):
        status += ' · глобальная пауза'
    updated = data.get('updated_ms')
    age = max(0, int(time.time()-updated/1000)) if updated else None
    stale = age is None or age>120 or bool(data.get('last_error'))
    freshness = (f'{age} с назад' if age is not None else 'ещё нет данных')
    if stale:
        freshness += ' · ВНИМАНИЕ: данные устарели или цикл завершился с ошибкой'
    fig.text(.10, .86, f'Капитал {capital} / $15 · {holding} · закрыто сделок: {len(wallet.get("trades", []))}', fontsize=11, parse_math=False)
    fig.text(.10, .81, status, fontsize=10)
    fig.text(.10, .76, 'Обновлено: '+freshness, fontsize=9, color='#bb3333' if stale else '#555555')
    candidate = data.get('candidate')
    if candidate:
        fig.text(.10, .71, f"Кандидат: {candidate['symbol']} {'LONG' if candidate['side']>0 else 'SHORT'}", fontsize=10)
    fig.text(.10, .05, 'Только живой PAPER-кошелёк · реальные ордера отключены\nhttp://192.168.0.8:8765/adaptive', fontsize=9, color='#555555')
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
