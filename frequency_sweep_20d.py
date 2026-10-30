import json,pathlib,gzip
import portfolio_market
R=pathlib.Path(__file__).resolve().parent
ref=json.load(gzip.open(R/'data/portfolio/QUSDT.json.gz'))['trade'][-1920:]
rows=portfolio_market.candles('QUSDT','kline',ref[0][0],ref[-1][0]+14*60000,interval=1)
assert len(rows)==28800,len(rows)
FEE=.001;SLIP=.0005
cases=[]
for side in (1,-1):
 for threshold in (.002,.003,.004,.005,.006,.007,.009,.012,.016,.022,.03,.04,.06):
  for volfactor in (1.,1.3,1.6,2.):
   cash=15.;pos=None;count=0;fees=0.;slippage=0.;cool=0
   for i in range(30,len(rows)-1):
    bar=rows[i];close=bar[4];nxt=rows[i+1][1]
    if pos is None:
     if i<cool:continue
     momentum=side*(close/rows[i-3][4]-1)
     prior=sum(r[6] for r in rows[i-20:i])/20
     volume=bar[6]/prior if prior else 0
     if momentum>threshold and volume>volfactor and side*(close/rows[i-1][4]-1)>0:
      px=nxt*(1+side*SLIP);qty=cash*(1-FEE)/px
      pos={'entry':px,'qty':qty,'capital':cash,'peak':close,'start':i+1}
      fees+=cash*FEE;slippage+=cash*SLIP
    else:
     age=i-pos['start'];pos['peak']=max(pos['peak'],close) if side==1 else min(pos['peak'],close)
     weakening=age>=2 and side*(close/rows[i-2][4]-1)<-.003 and side*(close/pos['entry']-1)>.004
     trail=side*(close/pos['peak']-1)<-.017
     stop=side*(close/pos['entry']-1)<-.025
     if weakening or trail or stop or age>=90:
      exitpx=nxt*(1-side*SLIP)
      gross=pos['qty']*side*(exitpx-pos['entry'])
      exitfee=pos['qty']*exitpx*FEE;fees+=exitfee;slippage+=pos['qty']*nxt*SLIP
      cash=max(0.,pos['capital']+gross-pos['capital']*FEE-exitfee)
      count+=1;pos=None;cool=i+3
      if cash<=0:break
   if pos:
    exitpx=rows[-1][4]*(1-side*SLIP)
    gross=pos['qty']*side*(exitpx-pos['entry'])
    exitfee=pos['qty']*exitpx*FEE;fees+=exitfee;slippage+=pos['qty']*rows[-1][4]*SLIP
    cash=max(0.,pos['capital']+gross-pos['capital']*FEE-exitfee);count+=1
   cases.append(dict(side='Long' if side==1 else 'Short',threshold=threshold,volume=volfactor,trades=count,capital=round(cash,5),fees=round(fees,4),slippage=round(slippage,4)))
print('CASES',len(cases),flush=True)
(R/'artifacts'/'frequency_sweep_20d.json').write_text(json.dumps(cases))
page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>QUSDT Частота / капитал</title>
<style>body{font:14px system-ui;background:#101827;color:#e8ecf3;margin:0}main{max-width:1150px;margin:auto;padding:18px}p{color:#adbed1}section{background:#1a293e;border-radius:12px;padding:15px;margin:16px 0}canvas{width:100%;height:430px;touch-action:pan-y}table{border-collapse:collapse;width:100%;font-size:12px}td,th{padding:6px;border-bottom:1px solid #345;text-align:right}td:first-child,th:first-child{text-align:left}a{color:#99ccff}</style>
<main><h1>QUSDT: капитал против частоты торговли</h1><p>20 дней · 9–29 октября 2026 · 28 800 настоящих минутных свечей. 104 независимых теста с разными порогами импульса и объёма, а не удаление сделок из истории.</p>
<section><h2>Y — капитал, X — число сделок</h2><canvas id="g"></canvas><p>🟢 Long · 🟠 Short · Белая линия: $15 (безубыточность). Красная линия: $15 − 0,03 × количество сделок (справочная комиссия при неизменном номинале $15). Реальные комиссии каждой точки посчитаны с изменением капитала.</p><p id="picked">Нажми на точку, чтобы увидеть её параметры.</p></section><section><h2>Лучшие варианты (выбраны задним числом)</h2><p id="best"></p><div style="overflow:auto"><table><thead><tr><th>Направление</th><th>Сделки</th><th>Капитал</th><th>Комиссии</th><th>Проскальзывание</th><th>Импульс 3м</th><th>Объём ×</th></tr></thead><tbody id="rows"></tbody></table></div></section><p>Вход и выход на открытии следующей минуты. Taker fee 0,10% за сторону (подтверждён только для SOLUSDT), проскальзывание 0,05% за сторону. Плечо 1×. Без funding, проверки минимального размера ордера, ликвидаций и реальной глубины стакана. Это сравнение по изученной истории, не прогноз.</p><a href="/predicted_extrema_20d.html">Минутный тест</a> · <a href="/oracle_20d.html">Идеальный эталон</a></main>
<script>const D=__DATA__,c=document.getElementById('g'),g=c.getContext('2d');let dots=[];let maxX=Math.max(...D.map(a=>a.trades)),minY=Math.min(0,15-.03*maxX,...D.map(a=>a.capital)),maxY=Math.max(16,...D.map(a=>a.capital));
function draw(){let w=c.clientWidth,h=c.clientHeight,d=devicePixelRatio||1;c.width=w*d;c.height=h*d;g.scale(d,d);const L=55,R=w-12,T=20,B=h-36;let X=n=>L+n/maxX*(R-L),Y=n=>B-(n-minY)/(maxY-minY)*(B-T);g.font='11px system-ui';for(let i=0;i<=5;i++){let v=minY+(maxY-minY)*i/5;g.strokeStyle='#345';g.beginPath();g.moveTo(L,Y(v));g.lineTo(R,Y(v));g.stroke();g.fillStyle='#bcd';g.fillText(v.toFixed(1),3,Y(v));g.fillText(Math.round(maxX*i/5),X(maxX*i/5)-8,h-12)}for(let [f,color] of [[x=>15,'#fff'],[x=>15-.03*x,'#ff6565']]){g.strokeStyle=color;g.setLineDash([4,5]);g.beginPath();g.moveTo(X(0),Y(f(0)));g.lineTo(X(maxX),Y(f(maxX)));g.stroke()}g.setLineDash([]);dots=[];for(let a of D){let x=X(a.trades),y=Y(a.capital);dots.push({a,x,y});g.fillStyle=a.side==='Long'?'#63e4a4':'#ffb266';g.globalAlpha=.72;g.beginPath();g.arc(x,y,4,0,7);g.fill()}g.globalAlpha=1}
function pick(e){let r=c.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top,p=[...dots].sort((a,b)=>Math.hypot(a.x-x,a.y-y)-Math.hypot(b.x-x,b.y-y))[0];if(p&&Math.hypot(p.x-x,p.y-y)<26)document.getElementById('picked').textContent=p.a.side+' | '+p.a.trades+' сделок | капитал $'+p.a.capital+' | комиссии $'+p.a.fees+' | импульс '+(p.a.threshold*100).toFixed(2)+'% | объём ×'+p.a.volume}
c.addEventListener('click',pick);window.addEventListener('resize',draw);draw();document.getElementById('best').textContent=['Long','Short'].map(s=>{let a=D.filter(x=>x.side===s).sort((x,y)=>y.capital-x.capital)[0];return s+': $'+a.capital+' за '+a.trades+' сделок'}).join(' | ');document.getElementById('rows').innerHTML=[...D].sort((a,b)=>a.trades-b.trades).map(a=>'<tr><td>'+a.side+'</td><td>'+a.trades+'</td><td>$'+a.capital+'</td><td>$'+a.fees+'</td><td>$'+a.slippage+'</td><td>'+(a.threshold*100).toFixed(2)+'%</td><td>'+a.volume+'</td></tr>').join('');</script></html>'''
(R/'artifacts'/'frequency_sweep_20d.html').write_text(page.replace('__DATA__',json.dumps(cases)))
for side in ('Long','Short'):
 group=[a for a in cases if a['side']==side];print(side,'trade_range',min(a['trades'] for a in group),max(a['trades'] for a in group),'best',max(group,key=lambda a:a['capital']),flush=True)
print('READY',flush=True)
