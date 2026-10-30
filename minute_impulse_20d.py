#!/usr/bin/env python3
import json,gzip,pathlib,sqlite3
from datetime import datetime,timezone
import portfolio_market
ROOT=pathlib.Path(__file__).resolve().parent
OUT=ROOT/'artifacts'
SYMS=('QUSDT','INITUSDT','1000PEPEUSDT')
# Fetch historical 1m actual bars, use only completed bars.
fee=.001;slip=.0005
result={}
for sym in SYMS:
    original=json.load(gzip.open(ROOT/'data/portfolio'/f'{sym}.json.gz'))['trade'][-1920:]
    start=original[0][0];end=original[-1][0]+14*60000
    print('FETCH',sym,flush=True)
    rows=portfolio_market.candles(sym,'kline',start,end,interval=1)
    rows=[r for r in rows if start<=r[0]<=end]
    if len(rows)<20000: raise RuntimeError(f'Incomplete {sym}: {len(rows)}')
    print('GOT',sym,len(rows),flush=True)
    # Every decision uses finalized preceding candles only. Orders on next open.
    capital=15.;position=None;trades=[];curve=[[rows[0][0],capital]];fees=0.;cool=0
    for i in range(30,len(rows)-1):
        ts,o,hi,lo,close,*_=rows[i]
        nextbar=rows[i+1]; nxt_open=nextbar[1]
        closes=[r[4] for r in rows[i-30:i+1]]
        vols=[r[6] for r in rows[i-30:i+1]]
        short_low=min(r[3] for r in rows[i-10:i])
        if position is None:
            if i<cool:continue
            # Impulse recognition: price recovers from dip, 3-minute acceleration, volume boost.
            m3=close/rows[i-3][4]-1
            prior_vol=sum(vols[-21:-1])/20
            active=vols[-1]>prior_vol*1.6 if prior_vol else False
            rebound=close/short_low-1
            if m3>.007 and close>rows[i-1][4] and .003<rebound<.065 and active:
                entry=nxt_open*(1+slip)
                q=(capital*(1-fee))/entry
                fees+=capital*fee
                position={'q':q,'entry':entry,'capital':capital,'ts':nextbar[0],'peak':entry,'start':i+1}
        else:
            position['peak']=max(position['peak'],close)
            age=i-position['start']
            # Adaptive exit: weakening 2-minute momentum after substantial gain, 1.7% trailing
            # or hard stop 2.5%; no future information and no intrabar stop fill claims.
            weakening=age>=2 and close<rows[i-2][4]*.997 and close>position['entry']*1.004
            trailing=close<position['peak']*.983
            stop=close<position['entry']*.975
            if weakening or trailing or stop or age>=90:
                exitprice=nxt_open*(1-slip)
                gross=position['q']*exitprice
                feeval=gross*fee;fees+=feeval
                capital=gross-feeval
                reason='weakening' if weakening else 'trail' if trailing else 'stop' if stop else 'timeout'
                trades.append(dict(buy=[position['ts'],position['entry']],sell=[nextbar[0],exitprice],net=capital-position['capital'],percent=100*(capital/position['capital']-1),reason=reason))
                curve.extend([[position['ts'],position['capital']],[nextbar[0],capital]])
                position=None;cool=i+3
    if position:
        exitprice=rows[-1][4]*(1-slip);gross=position['q']*exitprice;fees+=gross*fee;capital=gross*(1-fee)
        trades.append(dict(buy=[position['ts'],position['entry']],sell=[rows[-1][0],exitprice],net=capital-position['capital'],percent=100*(capital/position['capital']-1),reason='end'))
        curve.extend([[position['ts'],position['capital']],[rows[-1][0],capital]])
    curve.append([rows[-1][0],capital])
    # Reduce 1m points only for display. Trades retained at full resolution.
    result[sym]=dict(candles=[[r[0],r[4]] for r in rows[::5]],equity=curve,trades=trades,final=capital,fee=fees)
    print('DONE',sym,'trades',len(trades),'capital',round(capital,2),'fees',round(fees,3),flush=True)
orig=(OUT/'predicted_extrema_20d.html').read_text()
import re
orig=re.sub(r'const DATA=.*?;\nconst fmt=', 'const DATA='+json.dumps(result,separators=(',',':'))+';\nconst fmt=',orig,flags=re.S)
orig=orig.replace('Предполагаемые экстремумы · 20 дней','Минутные импульсы · 20 дней')
orig=orig.replace('Реальные 15-минутные свечи Bybit.','Реальные минутные свечи Bybit, отображается каждая пятая точка.')
orig=orig.replace('15-минутной свечи','минутной свечи')
orig=orig.replace('Вход: цена отскочила на 3% от минимума предыдущих 16 свечей, последняя свеча растёт более чем на 0,4%, цена не выше локального максимума на 14%. Выход: откат 6% от максимума после входа или стоп −8%.','Вход: рост за 3 минуты более 0,7%, повышенный объём более 1,6× среднего, восстановление от минимума 10 минут на 0,3–6,5%. Выход: ослабление импульса, откат 1,7% от максимума, стоп 2,5% либо 90 минут. Решения принимаются после закрытия минутной свечи, сделки исполняются на следующем открытии.')
orig=orig.replace('Ставка taker 0,10% взята из сохранённого API-ответа для SOLUSDT, для остальных инструментов не подтверждена.','Ставка taker 0,10% взята из сохранённого API-ответа для SOLUSDT, для остальных инструментов не подтверждена.')
(OUT/'predicted_extrema_20d.html').write_text(orig)
print('PAGE READY',flush=True)
