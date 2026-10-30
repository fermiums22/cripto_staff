"""Private-chat control, explicit numeric allowlist, paper pause/resume only."""
import json
import logging
import os
import sqlite3
import time
import urllib.request
import uuid
from contextlib import closing

import agent
import dashboard

TOKEN_FILE = agent.ROOT/'secrets/telegram.token'
ACCESS_FILE = agent.ROOT/'secrets/telegram-access.json'
BUTTONS = {'keyboard': [['Статус', 'График'], ['Пауза', 'Продолжить'],
                        ['Уведомления ВКЛ', 'Уведомления ВЫКЛ']], 'resize_keyboard': True}


def authorized(message, access):
    sender = message.get('from', {})
    chat = message.get('chat', {})
    return (chat.get('type') == 'private' and not sender.get('is_bot', True)
            and sender.get('id') == chat.get('id')
            and sender.get('id') in access.get('user_ids', []))


def action_for(message, access):
    text = message.get('text', '').strip()
    if message.get('chat', {}).get('type') != 'private':
        return 'deny'
    if text.split('@')[0] == '/id':
        return 'id'
    if not authorized(message, access):
        return 'deny'
    return {'/start': 'status', '/status': 'status', 'Статус': 'status',
            '/chart': 'chart', 'График': 'chart', '/pause': 'pause', '/stop': 'pause',
            'Пауза': 'pause', '/resume': 'resume', 'Продолжить': 'resume',
            '/notify_on': 'notify_on', 'Уведомления ВКЛ': 'notify_on',
            '/notify_off': 'notify_off', 'Уведомления ВЫКЛ': 'notify_off'}.get(text, 'help')


def notification_schema(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER PRIMARY KEY, enabled INTEGER, cursor INTEGER);
      CREATE TABLE IF NOT EXISTS deliveries (user_id INTEGER, event_id INTEGER, status TEXT,
        PRIMARY KEY(user_id,event_id));
      CREATE TABLE IF NOT EXISTS adaptive_bridge (event_id INTEGER PRIMARY KEY);
    ''')


def subscribe(db, user_id, enabled):
    with db:
        latest = db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
        current = db.execute('SELECT enabled FROM subscriptions WHERE user_id=?', (user_id,)).fetchone()
        if current and bool(current[0]) == enabled:
            return
        db.execute('INSERT OR REPLACE INTO subscriptions VALUES (?,?,?)', (user_id, int(enabled), latest))


def trade_text(kind, payload):
    p = json.loads(payload)
    if p.get('strategy') == 'adaptive':
        side = 'LONG' if p['side']>0 else 'SHORT'
        head = f"АДАПТИВНЫЙ PAPER · {p['symbol']} {side}\nСтратегия: {p['strategy_name']}"
        if kind == 'paper_entry':
            return (head+f"\nВИРТУАЛЬНЫЙ ВХОД · цена {p['entry']:.6f}\nОбъём: {p['qty']:.8f}"
                    +f"\nМаржа: {p['margin']:.4f} USDT · комиссия: {p['fees']:.4f} USDT")
        return (head+f"\nВИРТУАЛЬНЫЙ ВЫХОД · {p['exit_reason']}\nЧистый результат: {p['net']:+.4f} USDT"
                +f"\nКомиссии: {p['fees']:.4f} · funding: {p['funding']:+.4f} USDT"
                +f"\nКошелёк: {p['balance']:.4f} USDT\nЭто не реальные деньги.")
    strategy='\nСтратегия: '+p.get('strategy_name','Базовая ML-модель')
    if kind == 'paper_entry':
        return (f"ВИРТУАЛЬНЫЙ ВХОД · {p['symbol']}"+strategy+f"\nЦена: {p['entry']:.6f}"
                f"\nОбъём: {p['qty']:.8f}\nЗатрачено с комиссией: {p['cost']:.4f} USDT")
    pct = p['pnl_usdt']/p['cost']*100 if p['cost'] else 0
    reason = {'take': 'Take Profit', 'stop': 'Stop Loss', 'timeout': 'Лимит времени'}.get(p['reason'], p['reason'])
    return (f"ВИРТУАЛЬНЫЙ ВЫХОД · {p['symbol']}"+strategy+f"\nПричина: {reason}"
            f"\nЧистый результат: {p['pnl_usdt']:+.4f} USDT ({pct:+.2f}%)"
            '\nКомиссии и проскальзывание учтены. Это не реальные деньги.')


def bridge_adaptive_events(db):
    """Import durable PAPER events once; never reconstruct trades from counters."""
    path = agent.DATA/'adaptive.sqlite3'
    if not path.exists():
        return
    cursor = db.execute('SELECT COALESCE(MAX(event_id),0) FROM adaptive_bridge').fetchone()[0]
    with closing(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=5)) as source:
        if not source.execute("SELECT 1 FROM sqlite_master WHERE name='events'").fetchone():
            return
        rows = source.execute('SELECT id,ts,kind,payload FROM events WHERE id>? ORDER BY id LIMIT 100',(cursor,)).fetchall()
    with db:
        for event_id,ts,kind,payload in rows:
            if db.execute('INSERT OR IGNORE INTO adaptive_bridge VALUES (?)',(event_id,)).rowcount:
                db.execute('INSERT INTO events(ts,kind,payload) VALUES (?,?,?)',(ts,kind,payload))


def deliver_notifications(db, token, access, strategy=None):
    for uid, cursor in db.execute('SELECT user_id,cursor FROM subscriptions WHERE enabled=1').fetchall():
        if uid not in access.get('user_ids', []):
            continue
        query = "SELECT id,kind,payload FROM events WHERE id>? AND kind IN ('paper_entry','paper_exit')"
        params = [cursor]
        if strategy is not None:
            query += " AND json_extract(payload,'$.strategy')=?"
            params.append(strategy)
        events = db.execute(query+' ORDER BY id LIMIT 20',params).fetchall()
        for event_id, kind, payload in events:
            with db:
                fresh = db.execute("INSERT OR IGNORE INTO deliveries VALUES (?,?,'sending')", (uid,event_id)).rowcount
                db.execute('UPDATE subscriptions SET cursor=? WHERE user_id=?', (event_id,uid))
            if not fresh:
                continue
            try:
                call(token, 'sendMessage', {'chat_id': uid, 'text': trade_text(kind, payload)})
                state = 'sent'
            except Exception:
                state = 'unknown'
                logging.error('Trade notification delivery unconfirmed; not resent automatically')
            with db:
                db.execute('UPDATE deliveries SET status=? WHERE user_id=? AND event_id=?', (state,uid,event_id))


def set_paused(db, paused):
    with db:
        db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                   ('control', json.dumps({'paused': paused, 'updated_ms': int(time.time()*1000)})))


def call(token, method, data, photo=None):
    if photo is None:
        body = json.dumps(data).encode()
        content_type = 'application/json'
    else:
        boundary = uuid.uuid4().hex
        parts = []
        for key, value in data.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="paper.png"\r\nContent-Type: image/png\r\n\r\n'.encode()+photo+b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        body = b''.join(parts)
        content_type = 'multipart/form-data; boundary='+boundary
    request = urllib.request.Request('https://api.telegram.org/bot'+token+'/'+method,
                                     data=body, headers={'Content-Type': content_type})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=40) as response:
            result = json.load(response)
    except Exception:
        # HTTP exceptions can embed the bot token URL. Never log their text.
        raise RuntimeError('Telegram request failed') from None
    if not result.get('ok'):
        raise RuntimeError('Telegram rejected request')
    return result['result']


def status_text():
    path = agent.ARTIFACTS/'adaptive_live.json'
    if not path.exists():
        return 'Адаптивный PAPER: ожидание данных сервиса.\nПанель: http://192.168.0.8:8765/adaptive'
    data = json.loads(path.read_text(encoding='utf-8')); wallet = data.get('wallet', {})
    points = wallet.get('curve', []); equity = data.get('equity', points[-1][1] if points else None)
    capital = f'{equity:.4f} USDT' if equity is not None else 'нет данных'
    updated = data.get('updated_ms'); age = max(0,int(time.time()-updated/1000)) if updated else None
    pos = wallet.get('position'); trades = wallet.get('trades', [])
    holding = f"{pos['symbol']} {'LONG' if pos['side']>0 else 'SHORT'}" if pos else 'нет'
    if not data.get('live_gate'):
        state = 'сбор данных; входы заблокированы — отбор убыточен'
    elif data.get('paused'):
        state = 'глобальная пауза входов'
    elif wallet.get('halted'):
        state = 'лимит риска; новые входы запрещены'
    else:
        state = 'позиция под контролем' if pos else 'ожидание сигнала после издержек'
    lines = ['Адаптивный PAPER · '+data.get('selected','ожидание отбора'),
             'Капитал: '+capital+' / старт 15 USDT', 'Состояние: '+state,
             'Позиция: '+holding, f'Закрыто сделок: {len(trades)}',
             f"Чистый результат закрытых сделок: {sum(t['net'] for t in trades):+.4f} USDT",
             'Последний цикл: '+(f'{age} с назад' if age is not None else 'нет данных')]
    candidate = data.get('candidate')
    if candidate:
        lines.append(f"Кандидат: {candidate['symbol']} {'LONG' if candidate['side']>0 else 'SHORT'}; это ещё не вход")
    if data.get('paused') and not data.get('live_gate'):
        lines.append('Дополнительно включена глобальная пауза.')
    if age is None or age>120 or data.get('last_error'):
        lines.append('ВНИМАНИЕ: данные устарели или цикл завершился с ошибкой.')
    lines.append('Реальные ордера отключены.\nПанель: http://192.168.0.8:8765/adaptive')
    return '\n'.join(lines)


def main():
    os.umask(0o077)
    token = TOKEN_FILE.read_text().strip()
    with agent.connect() as db:
        notification_schema(db)
        while True:
            try:
                bridge_adaptive_events(db)
                row = db.execute("SELECT value FROM state WHERE key='telegram_offset'").fetchone()
                offset = int(row[0]) if row else 0
                updates = call(token, 'getUpdates', {'offset': offset, 'timeout': 3, 'allowed_updates': ['message']})
                for update in updates:
                    message = update.get('message', {})
                    access = json.loads(ACCESS_FILE.read_text()) if ACCESS_FILE.exists() else {'user_ids': []}
                    action = action_for(message, access)
                    # Controls are idempotent; never interpret messages as shell commands.
                    chat = message.get('chat', {}).get('id')
                    text = None
                    if action == 'id':
                        text = 'Твой Telegram user ID: '+str(message['from']['id'])+'\nПередай число Виктору для белого списка.'
                    elif action == 'deny':
                        if message.get('chat', {}).get('type') == 'private':
                            text = 'Нет доступа. Команда /id покажет ID для белого списка.'
                    elif action in ('pause', 'resume'):
                        set_paused(db, action == 'pause')
                        text = ('Новые входы остановлены. Выход из открытой виртуальной позиции остаётся под контролем.'
                                if action == 'pause' else 'Глобальная пауза снята. Входы адаптивного PAPER требуют допуска отбора и лимитов риска. Реальные ордера выключены.')
                    elif action == 'status':
                        text = status_text()
                        sub = db.execute('SELECT enabled FROM subscriptions WHERE user_id=?', (chat,)).fetchone()
                        text += '\nУведомления адаптивного PAPER: '+('ВКЛ' if sub and sub[0] else 'ВЫКЛ')
                        delivery = db.execute("SELECT d.status FROM deliveries d JOIN events e ON e.id=d.event_id WHERE d.user_id=? AND json_extract(e.payload,'$.strategy')='adaptive' ORDER BY e.id DESC LIMIT 1",(chat,)).fetchone()
                        if delivery:
                            text += '\nПоследнее уведомление: '+{'sent':'отправлено','unknown':'доставка не подтверждена','sending':'доставка не подтверждена'}.get(delivery[0],delivery[0])
                    elif action in ('notify_on', 'notify_off'):
                        bridge_adaptive_events(db)
                        subscribe(db, chat, action == 'notify_on')
                        text = ('Уведомления о новых входах и выходах адаптивного PAPER включены. Старые сделки не пересылаются.'
                                if action == 'notify_on' else 'Уведомления выключены для этого аккаунта.')
                    elif action == 'chart':
                        call(token, 'sendPhoto', {'chat_id': chat, 'caption': 'Адаптивный PAPER · текущий общий кошелёк $15\nСостояние и свежесть данных — на графике. Реальные ордера отключены.'}, dashboard.graph_png())
                    elif action == 'help':
                        text = '/status — состояние\n/chart — график\n/pause — пауза входов\n/resume — продолжить'
                    if text:
                        payload = {'chat_id': chat, 'text': text}
                        if authorized(message, access):
                            payload['reply_markup'] = BUTTONS
                        call(token, 'sendMessage', payload)
                    with db:
                        db.execute("INSERT OR REPLACE INTO state VALUES ('telegram_offset',?)", (str(update['update_id']+1),))
                access = json.loads(ACCESS_FILE.read_text()) if ACCESS_FILE.exists() else {'user_ids': []}
                bridge_adaptive_events(db)
                deliver_notifications(db, token, access, strategy='adaptive')
            except Exception as exc:
                logging.error('Telegram cycle error: %s', type(exc).__name__)
                time.sleep(5)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
