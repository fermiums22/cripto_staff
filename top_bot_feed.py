"""Read-only PAPER event feed for the current leading active arena strategy."""
import json, sqlite3, time
from pathlib import Path
import agent, telegram_control as tg
ROOT=agent.ROOT
STATE=ROOT/'data/top_bot_feed_cursor.json'
TOP='hb_bollinger'
def run():
    token=tg.TOKEN_FILE.read_text().strip()
    access=json.loads(tg.ACCESS_FILE.read_text())
    db=sqlite3.connect('file:'+str(agent.DATA/'agent.sqlite3')+'?mode=ro',uri=True,timeout=10)
    last=json.loads(STATE.read_text())['cursor'] if STATE.exists() else db.execute('select coalesce(max(id),0) from events').fetchone()[0]
    if not STATE.exists():STATE.write_text(json.dumps({'cursor':last}))
    # Inform opted-in users at startup.
    for uid,enabled in db.execute('select user_id,enabled from subscriptions').fetchall():
        if enabled and uid in access.get('user_ids',[]):
            try:tg.call(token,'sendMessage',{'chat_id':uid,'text':'🏆 PAPER · лента лидера: Hummingbot Bollinger. Показываю только новые виртуальные входы/выходы; реальные деньги не используются. /notify_off отключает уведомления.'})
            except Exception:pass
    while True:
        for event_id,kind,payload in db.execute("select id,kind,payload from events where id>? and kind in ('paper_entry','paper_exit') order by id limit 100",(last,)).fetchall():
            last=event_id
            try:p=json.loads(payload)
            except ValueError:continue
            if p.get('strategy')==TOP:
                for uid,enabled in db.execute('select user_id,enabled from subscriptions').fetchall():
                    if enabled and uid in access.get('user_ids',[]):
                        try:tg.call(token,'sendMessage',{'chat_id':uid,'text':'🏆 ЛИДЕР PAPER\n'+tg.trade_text(kind,payload)})
                        except Exception:pass
            STATE.write_text(json.dumps({'cursor':last}))
        time.sleep(5)
if __name__=='__main__':run()
