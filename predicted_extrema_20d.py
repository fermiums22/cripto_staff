#!/usr/bin/env python3
"""Causal signals, next-bar-open fills; create separate page, preserve oracle."""
import json,re,pathlib,html,gzip
root=pathlib.Path(__file__).resolve().parent
out={}
for sym in ('QUSDT','INITUSDT','1000PEPEUSDT'):
    bars=json.load(gzip.open(root/'data/portfolio'/f'{sym}.json.gz'))['trade'][-1920:]
    trades=[];eq=15.;fee_paid=0.;state=None;cooldown=0; curve=[[bars[0][0],eq]]
    # Fixed parameters across coins, no future info in decisions.
    # 16 bar prior low, price at least 3% above; 6% trailing exit, 8% hard stop.
    for i in range(17,len(bars)-1):
        t,o,h,l,c,*_=bars[i]
        nxt=bars[i+1]
        if state is None:
            if i<cooldown:continue
            low=min(b[3] for b in bars[i-16:i])
            high=max(b[2] for b in bars[i-16:i])
            # A local low was observed in the preceding bars; rising from low and some momentum
            if c>=low*1.03 and c>bars[i-1][4]*1.004 and c<high*1.14:
                fill=nxt[1]*1.0005
                fee=eq*.001;fee_paid+=fee
                qty=(eq-fee)/fill
                state=dict(qty=qty,capital=eq,entry=fill,entry_ts=nxt[0],peak=c,entry_index=i+1)
                eq=0
        else:
            state['peak']=max(state['peak'],c)
            stop=c<=state['entry']*.92
            trail=c<=state['peak']*.94
            if stop or trail:
                exit_price=nxt[1]*.9995
                gross=state['qty']*exit_price
                fee=gross*.001;fee_paid+=fee
                eq=gross-fee
                trades.append(dict(buy=[state['entry_ts'],state['entry']],sell=[nxt[0],exit_price],net=eq-state['capital'],percent=(eq/state['capital']-1)*100,reason='stop' if stop else 'trailing'))
                curve.extend([[state['entry_ts'],state['capital']],[nxt[0],eq]])
                state=None;cooldown=i+5
    if state:
        exit_price=bars[-1][4]*.9995;gross=state['qty']*exit_price;fee=gross*.001;fee_paid+=fee
        eq=gross-fee;trades.append(dict(buy=[state['entry_ts'],state['entry']],sell=[bars[-1][0],exit_price],net=eq-state['capital'],percent=(eq/state['capital']-1)*100,reason='end'))
        curve.extend([[state['entry_ts'],state['capital']],[bars[-1][0],eq]])
    curve.append([bars[-1][0],eq])
    out[sym]=dict(candles=[[b[0],b[4]] for b in bars],equity=curve,trades=trades,final=eq,fee=fee_paid)
src=(root/'artifacts/oracle_20d.html').read_text()
# Reuse exact chart code/layout while publishing a different file, never overwrite ideal baseline.
src=src.replace('Идеальная торговля · 20 дней','Предполагаемые экстремумы · 20 дней')
src=src.replace('Реальные 15-минутные свечи из архива Bybit. <strong class="orange">ORACLE / подглядывание в будущее:</strong> входы и выходы размечены после просмотра всей истории. Это иллюстрация потолка, не торгуемая стратегия.','Реальные 15-минутные свечи Bybit. <strong class="green">Без подглядывания в будущее:</strong> решения только по уже закрытым свечам, исполнение на открытии следующей. Фиксированные правила без оптимизации.')
src=src.replace('Цена: зелёный — покупка, оранжевый — продажа','Цена: входы по предполагаемым минимумам, выход по trailing stop')
src=src.replace('Один актив, long-only, плечо 1×, весь доступный капитал на каждую сделку, без одновременных позиций. Вне позиции капитал постоянен.','Один актив, long-only, 1×. Не более одной позиции. Моделируемая комиссия 0,10% и проскальзывание 0,05% на сторону.')
src=src.replace('Вне позиции капитал постоянен.','Вне позиции капитал постоянен.')
src=src.replace('Для 15-минутных OHLC нет подтверждённых исполнимых котировок: используются цены закрытия свечей, а ликвидность, шаги лота, биржевые минимумы, funding и влияние сделки на рынок не воспроизведены.','Исполнение на открытии следующей 15-минутной свечи, без знания этой цены во время принятия решения. Ликвидность, шаги лота, биржевые минимумы, funding и влияние сделки на рынок не воспроизведены.')
src=src.replace('Нет торговли и доступа к API-ключам.','Ставка taker 0,10% взята из сохранённого API-ответа для SOLUSDT, для остальных инструментов не подтверждена. Вход: цена отскочила на 3% от минимума предыдущих 16 свечей, последняя свеча растёт более чем на 0,4%, цена не выше локального максимума на 14%. Выход: откат 6% от максимума после входа или стоп −8%. Параметры не подгонялись, это только первый прототип. Нет реальных ордеров.')
src=src.replace('const DATA='+re.search(r'const DATA=(.*?);\nconst fmt=',src,re.S).group(1)+';','const DATA='+json.dumps(out,separators=(',',':'))+';')
src=src.replace('<a href="http://192.168.0.8:8765/">Вернуться к основной панели</a>','<a href="/oracle_20d.html">Идеальный тест (№1)</a> · <a href="http://192.168.0.8:8765/">Основная панель</a>')
src=src.replace('<th>Чистые USDT</th>','<th>Чистые USDT</th>')
(root/'artifacts'/'predicted_extrema_20d.html').write_text(src)
for s,v in out.items():print(s,len(v['trades']),round(v['final'],2),round(v['fee'],3))
