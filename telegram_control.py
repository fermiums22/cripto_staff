"""Private-chat control, explicit numeric allowlist, paper pause/resume only."""
import json
import hashlib
import hmac
import urllib.parse
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
    strategy='\nСтратегия: '+p.get('strategy_name','Базовая ML-модель')
    if kind == 'paper_entry':
        return (f"ВИРТУАЛЬНЫЙ ВХОД · {p['symbol']}"+strategy+f"\nЦена: {p['entry']:.6f}"
                f"\nОбъём: {p['qty']:.8f}\nЗатрачено с комиссией: {p['cost']:.4f} USDT")
    pct = p['pnl_usdt']/p['cost']*100 if p['cost'] else 0
    reason = {'take': 'Take Profit', 'stop': 'Stop Loss', 'timeout': 'Лимит времени'}.get(p['reason'], p['reason'])
    return (f"ВИРТУАЛЬНЫЙ ВЫХОД · {p['symbol']}"+strategy+f"\nПричина: {reason}"
            f"\nЧистый результат: {p['pnl_usdt']:+.4f} USDT ({pct:+.2f}%)"
            '\nКомиссии и проскальзывание учтены. Это не реальные деньги.')


def deliver_notifications(db, token, access):
    for uid, cursor in db.execute('SELECT user_id,cursor FROM subscriptions WHERE enabled=1').fetchall():
        if uid not in access.get('user_ids', []):
            continue
        events = db.execute("SELECT id,kind,payload FROM events WHERE id>? AND kind IN ('paper_entry','paper_exit') ORDER BY id LIMIT 20", (cursor,)).fetchall()
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


def account_balance():
    """Read wallet compartments; no orders, transfers, or raw API error text."""
    try:
        _, key, secret = [v.strip() for v in (agent.ROOT/'secrets/bybit.key').read_text(encoding='utf-8-sig').splitlines()]
    except Exception:
        return 'ключ недоступен'
    def query(path, params):
        qs=urllib.parse.urlencode(params)
        ts=str(int(time.time()*1000)); window='5000'
        signature=hmac.new(secret.encode(), (ts+key+window+qs).encode(), hashlib.sha256).hexdigest()
        req=urllib.request.Request('https://api.bybit.com/v5/'+path+'?'+qs,headers={
            'X-BAPI-API-KEY':key,'X-BAPI-TIMESTAMP':ts,
            'X-BAPI-RECV-WINDOW':window,'X-BAPI-SIGN':signature})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=7) as response:
            data=json.load(response)
        if data.get('retCode')!=0:raise ValueError('API error')
        return data['result']
    lines=[]; incomplete=[]; total=0.
    for kind in ('UNIFIED','SPOT','CONTRACT'):
        try:
            info=query('account/wallet-balance',{'accountType':kind})['list'][0]
            equity=info.get('totalEquity')
            if equity is not None and equity!='':
                amount=float(equity); total+=amount
                lines.append(f'{kind}: {amount:.2f} USD')
            else:
                coins=[c for c in info.get('coin',[]) if float(c.get('walletBalance') or 0)>0]
                if coins:lines.append(kind+': '+', '.join(str(c['coin'])+' '+str(c['walletBalance']) for c in coins[:5]))
                incomplete.append(kind+' без оценки')
        except Exception:
            if kind=='UNIFIED':incomplete.append(kind+' недоступен')
    try:
        info=query('asset/transfer/query-account-coins-balance',{'accountType':'FUND'})
        coins=[c for c in info.get('balance',[]) if float(c.get('walletBalance') or 0)>0]
        if coins:
            lines.append('FUNDING: '+', '.join(str(c['coin'])+' '+str(c['walletBalance']) for c in coins[:6]))
            total+=sum(float(c['walletBalance']) for c in coins if c['coin']=='USDT')
            if any(c['coin']!='USDT' for c in coins):incomplete.append('Funding с другими активами')
        else:lines.append('FUNDING: 0')
    except Exception:
        incomplete.append('Funding недоступен')
    if not lines:return 'балансы недоступны'
    lines.append(f'Известная сумма: ≈{total:.2f} USD'+(' (неполная)' if incomplete else ''))
    if incomplete:lines.append('Ограничения: '+', '.join(incomplete))
    return '\n'.join(lines)


def status_text():
    data=dashboard.snapshot()
    state=data['status'];now=data['now_ms']
    age=max(0,(now-state.get('heartbeat_ms',0))//1000)
    arena={a['id']:a for a in data.get('arena',[])}
    leader=arena.get('hb_bollinger',{})
    pos=leader.get('position')
    reason={'waiting_signal':'ждёт входа','position_open':'держит позицию',
            'paused':'пауза','stale_quote':'нет свежих котировок',
            'loss_limit':'лимит убытков','cooldown':'перерыв после сделки',
            'minimum_order':'меньше минимального ордера'}.get(leader.get('reason'),leader.get('reason','неизвестно'))
    lines=['📊 Сводка Bybit · '+time.strftime('%d.%m %H:%M UTC',time.gmtime()),
           '💰 Реальный баланс: '+account_balance(),
           f"🧪 PAPER-лидер: Hummingbot Bollinger · {leader.get('equity',15):.4f} / 15 USDT",
           'Состояние: '+reason+(' · '+pos['symbol'] if pos else ''),
           f"Закрыто сделок: {leader.get('trades',0)}",
           f"Базовый ML: {state.get('equity_usdt',15):.4f} USDT · {'пауза' if state.get('paused') else 'работает'} · цикл {age}с"]
    scan_path=agent.ARTIFACTS/'market_scan.json'
    if scan_path.exists():
        try:
            scan=json.loads(scan_path.read_text())
            scan_age=(now-scan['observed_ms'])//60000
            bysymbol={v['symbol']:v for v in scan.get('rows',[])}
            lines.append(f"🎯 Монеты на прицеле (скан {scan_age} мин назад):")
            for sym in scan.get('watchlist',[])[:5]:
                r=bysymbol.get(sym,{})
                change=r.get('recent_move')
                spread=r.get('spread')
                lines.append(f"• {sym}: {change*100:+.2f}% / 5 мин" if isinstance(change,(int,float)) else f"• {sym}")
            if scan_age>30:lines.append('⚠️ Скан рынка устарел')
            lines.append(f"Рынок: {scan.get('scanned',0)} просмотрено, {scan.get('eligible',0)} прошло фильтры")
        except Exception:lines.append('Скан рынка: данные недоступны')
    lines.append('⚠️ Монеты из сканера — наблюдение, не подтверждённые сигналы к покупке.')
    if age>120:lines.append('⚠️ Основной PAPER-цикл устарел')
    lines.append('Панель: http://192.168.0.8:8765')
    return '\n'.join(lines)


def main():
    os.umask(0o077)
    token = TOKEN_FILE.read_text().strip()
    with agent.connect() as db:
        notification_schema(db)
        while True:
            try:
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
                                if action == 'pause' else 'Новые виртуальные входы разрешены. Реальные ордера выключены.')
                    elif action == 'status':
                        text = status_text()
                        sub = db.execute('SELECT enabled FROM subscriptions WHERE user_id=?', (chat,)).fetchone()
                        text += '\nУведомления: '+('ВКЛ' if sub and sub[0] else 'ВЫКЛ')
                    elif action in ('notify_on', 'notify_off'):
                        subscribe(db, chat, action == 'notify_on')
                        text = ('Уведомления о новых виртуальных входах и выходах включены для этого аккаунта.'
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
                deliver_notifications(db, token, access)
            except Exception as exc:
                logging.error('Telegram cycle error: %s', type(exc).__name__)
                time.sleep(5)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
