"""Collect timestamped news metadata for prospective research, not instant trading advice."""
import email.utils
import json
import sqlite3
import time
import urllib.request
import xml.etree.ElementTree as ET

import agent
from research_worker import write_json

FEEDS = {'CoinDesk':'https://www.coindesk.com/arc/outboundfeeds/rss/',
         'Federal Reserve':'https://www.federalreserve.gov/feeds/press_all.xml'}


def category(title):
    text=title.lower()
    if any(k in text for k in ('hack','exploit','breach','suspend','delist')):return 'security_or_restriction'
    if any(k in text for k in ('fomc','interest rate','monetary','inflation')):return 'macro'
    if any(k in text for k in ('listing','launch','list ')):return 'listing'
    if any(k in text for k in ('etf','sec ','regulat','court')):return 'regulation'
    return 'market'


def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':'CriptoStaff-Research/1.0'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=20) as r:
        return r.read(2000000)


def collect():
    agent.DATA.mkdir(exist_ok=True)
    db=sqlite3.connect(agent.DATA/'context.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS news(source TEXT,url TEXT PRIMARY KEY,title TEXT,published_ms INTEGER,first_seen_ms INTEGER,category TEXT)')
    now=int(time.time()*1000);status={}
    for source,url in {**FEEDS,'Bybit':'https://api.bybit.com/v5/announcements/index?locale=en-US&limit=50'}.items():
        try:
            raw=fetch(url);rows=[]
            if source=='Bybit':
                data=json.loads(raw)
                if data.get('retCode')!=0:raise RuntimeError('Announcement request rejected')
                rows=[(v['url'],v['title'],int(v.get('publishTime') or v.get('dateTimestamp') or now)) for v in data['result']['list']]
            else:
                for item in ET.fromstring(raw).findall('.//item')[:80]:
                    stamp=email.utils.parsedate_to_datetime(item.findtext('pubDate'))
                    rows.append((item.findtext('link',''),item.findtext('title',''),int(stamp.timestamp()*1000)))
            with db:
                for link,title,published in rows:
                    if link.startswith('https://') and title:
                        db.execute('INSERT OR IGNORE INTO news VALUES (?,?,?,?,?,?)',
                                   (source,link,title[:500],published,now,category(title)))
            status[source]={'ok':True,'fetched':len(rows)}
        except Exception as exc:
            status[source]={'ok':False,'error':type(exc).__name__}
    rows=db.execute('SELECT source,url,title,published_ms,first_seen_ms,category FROM news ORDER BY first_seen_ms DESC,published_ms DESC LIMIT 30').fetchall()
    report=dict(updated_ms=now,sources=status,mode='observation_only',
                items=[dict(zip(('source','url','title','published_ms','first_seen_ms','category'),r)) for r in rows],
                note='Заголовки классифицируются по теме. Это не оценка достоверности или торговый сигнал. Использовать только после first_seen_ms.')
    write_json(agent.ARTIFACTS/'market_context.json',report);db.close()
    print(json.dumps(status))


if __name__=='__main__':collect()
