"""Private-chat control, explicit numeric allowlist, paper pause/resume only."""
import json
import logging
import os
import time
import urllib.request
import uuid
from pathlib import Path

import agent
import dashboard

TOKEN_FILE = agent.ROOT/'secrets/telegram.token'
ACCESS_FILE = agent.ROOT/'secrets/telegram-access.json'
BUTTONS = {'keyboard': [['Статус', 'График'], ['Пауза', 'Продолжить']], 'resize_keyboard': True}


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
            'Пауза': 'pause', '/resume': 'resume', 'Продолжить': 'resume'}.get(text, 'help')


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
    data = dashboard.snapshot()
    state = data['status']
    age = max(0, (data['now_ms']-state.get('heartbeat_ms', 0))//1000)
    pos = state.get('portfolio', {}).get('position')
    return ('Только виртуальные сделки\n'
            + ('ПАУЗА новых входов' if state.get('paused') else 'Новые входы разрешены')
            + f"\nПоследний цикл: {age} с назад"
            + f"\nКапитал: {state.get('equity_usdt', 15):.4f} USDT"
            + f"\nPnL: {state.get('pnl_usdt', 0):+.4f} USDT"
            + f"\nПозиция: {pos['symbol'] if pos else 'нет'}"
            + ('\nВНИМАНИЕ: цикл устарел' if age > 120 else '')
            + ('\nОшибка получения данных' if state.get('last_error') else '')
            + '\nПанель дома/VPN: http://192.168.0.8:8765')


def main():
    os.umask(0o077)
    token = TOKEN_FILE.read_text().strip()
    with agent.connect() as db:
        while True:
            try:
                row = db.execute("SELECT value FROM state WHERE key='telegram_offset'").fetchone()
                offset = int(row[0]) if row else 0
                updates = call(token, 'getUpdates', {'offset': offset, 'timeout': 25, 'allowed_updates': ['message']})
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
                                if action == 'pause' else 'Новые виртуальные входы разрешены. Реальные ордера выключены.')
                    elif action == 'status':
                        text = status_text()
                    elif action == 'chart':
                        call(token, 'sendPhoto', {'chat_id': chat, 'caption': 'Реальные котировки · виртуальный капитал'}, dashboard.graph_png())
                    elif action == 'help':
                        text = '/status — состояние\n/chart — график\n/pause — пауза входов\n/resume — продолжить'
                    if text:
                        payload = {'chat_id': chat, 'text': text}
                        if authorized(message, access):
                            payload['reply_markup'] = BUTTONS
                        call(token, 'sendMessage', payload)
                    with db:
                        db.execute("INSERT OR REPLACE INTO state VALUES ('telegram_offset',?)", (str(update['update_id']+1),))
            except Exception as exc:
                logging.error('Telegram cycle error: %s', type(exc).__name__)
                time.sleep(5)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
