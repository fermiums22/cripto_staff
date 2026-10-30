import gzip,json,pathlib
import portfolio_market
R=pathlib.Path(__file__).resolve().parent
raw=json.load(gzip.open(R/'data/portfolio/QUSDT.json.gz'))['trade'][-1920:]
bars=portfolio_market.candles('QUSDT','kline',raw[0][0],raw[-1][0]+14*60000,interval=1)
assert len(bars)==28800
fee=.001; slip=.0005
results=[]
for side in (1,-1):
 for lev in (1,2,3,5,10):
  for threshold in (.004,.008,.015,.03):
   for grow in (False,True):
    cash=15.;pos=None;trades=0;fees=0.;peak=15.;dd=0.;liqs=0;adds=0;cool=0;curve=[[bars[0][0],15.]]
    for i in range(31,len(bars)-1):
     b=bars[i];nextopen=bars[i+1][1];close=b[4]
     if pos is None:
      if cash<.5 or i<cool:continue
      momentum=side*(close/bars[i-3][4]-1)
      prior=sum(r[6] for r in bars[i-20:i])/20
      if momentum>threshold and b[6]>prior*1.6 and side*(close/bars[i-1][4]-1)>0:
       margin=cash*.9; entry=nextopen*(1+side*slip)
       notional=margin*lev; entryfee=notional*fee
       cash-=margin+entryfee;fees+=entryfee
       pos={'qty':notional/entry,'entry':entry,'margin':margin,'start':i+1,'best':entry,'adds':0,'lastadd':i+1}
     else:
      p=pos
      p['best']=max(p['best'],close) if side==1 else min(p['best'],close)
      # adverse low/high to approximate intrabar liquidation, fee notional included
      adverse=b[3] if side==1 else b[2]
      equity=p['margin']+p['qty']*side*(adverse-p['entry'])
      if equity<=p['qty']*adverse*(.006+fee):
       liqs+=1;trades+=1;cash=max(0,cash);pos=None;cool=i+4;curve.append([b[0],cash]);continue
      # Only pyramid into winners, up to 2 additions; never average down
      gain=side*(close/p['entry']-1)
      if grow and p['adds']<2 and i-p['lastadd']>=3 and gain>(.008+.008*p['adds']) and cash>1:
       alloc=cash*.7;fill=nextopen*(1+side*slip);nom=alloc*lev;newfee=nom*fee
       if alloc+newfee<=cash:
        oldqty=p['qty'];p['qty']+=nom/fill;p['entry']=(oldqty*p['entry']+(nom/fill)*fill)/p['qty'];p['margin']+=alloc
        cash-=alloc+newfee;fees+=newfee;p['adds']+=1;p['lastadd']=i+1;adds+=1
      age=i-p['start']
      weakening=age>=2 and side*(close/bars[i-2][4]-1)<-.003 and gain>.004
      trail=side*(close/p['best']-1)<-.017
      stop=gain<-.025
      if weakening or trail or stop or age>=90:
       exitpx=nextopen*(1-side*slip)
       gross=p['qty']*side*(exitpx-p['entry'])
       exitfee=p['qty']*exitpx*fee;fees+=exitfee
       cash=max(0,cash+p['margin']+gross-exitfee);trades+=1;pos=None;cool=i+3
       curve.append([bars[i+1][0],cash]);peak=max(peak,cash);dd=max(dd,1-cash/peak)
    if pos:
     p=pos;px=bars[-1][4]*(1-side*slip);exitfee=p['qty']*px*fee;fees+=exitfee
     cash=max(0,cash+p['margin']+p['qty']*side*(px-p['entry'])-exitfee);trades+=1
    peak=max(peak,cash);dd=max(dd,1-cash/peak)
    curve.append([bars[-1][0],cash])
    results.append(dict(side='Long' if side==1 else 'Short',leverage=lev,pyramid=grow,threshold=threshold,capital=round(cash,4),trades=trades,fees=round(fees,4),liquidations=liqs,adds=adds,drawdown=round(100*dd,2),curve=curve))
    print(side,lev,threshold,grow,round(cash,2),trades,liqs,flush=True)
(R/'artifacts'/'aggressive_20d.json').write_text(json.dumps(results))
page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Тест №3 · Агрессивный капитал</title>
<style>body{margin:0;background:#101827;color:#ecf1f8;font:14px system-ui}main{max-width:1100px;margin:auto;padding:16px}h1{font-size:23px}p,small{color:#b1c0d1}section{padding:14px;margin:14px 0;background:#1a293e;border-radius:12px}canvas{width:100%;height:360px;touch-action:pan-y}table{width:100%;border-collapse:collapse;font-size:12px}td,th{border-bottom:1px solid #345;padding:6px;text-align:right}td:first-child,th:first-child{text-align:left}a{color:#99c9ff}select{background:#233951;color:white;padding:8px;border:1px solid #567;border-radius:6px}strong{color:#a3f3b8}</style>
<main><h1>Тест №3 · Атакуем импульсы</h1><p>QUSDT, 9–29 октября 2026. 80 экспериментов с плечом 1–10×, без и с добавлением к прибыльной позиции. Старт $15. Сигналы по закрытой минуте, исполнение на следующем открытии. Только синтетика.</p>
<section><h2>Результаты: капитал / сделки</h2><label>Масштаб <select id="mode"><option value="normal">Рабочая зона</option><option value="full">Полный</option><option value="log">Логарифм</option></select></label><canvas id="chart"></canvas><p>🟢 Long · 🟠 Short · ★ идеал $5 970 за 17 сделок (знание будущего). Белая линия $15. Нажми точку, чтобы увидеть параметры.</p><p id="selected"></p></section>
<section><h2>Лучшие и опасные сценарии</h2><p id="overview"></p><div style="overflow:auto"><table><thead><tr><th>Сторона</th><th>Плечо</th><th>Добавления</th><th>Сделки</th><th>Капитал</th><th>Комиссии</th><th>Ликвидации*</th><th>Просадка</th><th>Порог 3м</th></tr></thead><tbody id="tbody"></tbody></table></div></section>
<p>* Ликвидация приближённая: OHLC экстремум минуты и условная поддерживающая маржа 0,6%, без точного Bybit risk tier и intrabar-пути цены. Funding, минимальный объём, tick-size, динамический спред и влияние позиции на ликвидность не учтены. Taker 0,10% + проскальзывание 0,05% за сторону; комиссия подтверждена для SOL, для Q — сценарная. Подбор удачного варианта на той же истории не означает прогнозной прибыльности. Реальных сделок нет.</p><a href="/frequency_sweep_20d.html">Тест частоты №2</a> · <a href="/oracle_20d.html">Идеальный эталон</a></main><script>
const DATA=__DATA__,ideal={capital:5970.8,trades:17,side:'Идеал'};let pts=[];const el=document.querySelector('canvas'),g=el.getContext('2d'),maxX=Math.max(...DATA.map(a=>a.trades)),maxCap=Math.max(...DATA.map(a=>a.capital),15),baseMin=0;
function draw(){const mode=document.getElementById('mode').value,w=el.clientWidth,h=el.clientHeight,d=devicePixelRatio||1;el.width=w*d;el.height=h*d;g.scale(d,d);let l=55,r=w-14,t=15,b=h-40;let hi=mode==='full'?Math.max(ideal.capital,maxCap):mode==='log'?Math.log1p(Math.max(ideal.capital,maxCap)):Math.min(Math.max(30,maxCap),250);let X=x=>l+(x/maxX)*(r-l),Y=y=>b-(mode==='log'?Math.log1p(Math.max(0,y)):y)/hi*(b-t);g.font='11px system-ui';g.strokeStyle='#364c65';g.fillStyle='#bcd';for(let i=0;i<=5;i++){let v=mode==='log'?Math.expm1(hi*i/5):hi*i/5;g.beginPath();g.moveTo(l,Y(v));g.lineTo(r,Y(v));g.stroke();g.fillText(v.toFixed(0),3,Y(v)+4);g.fillText(Math.round(maxX*i/5),X(maxX*i/5)-8,h-10)}g.strokeStyle='#fff';g.setLineDash([5,5]);g.beginPath();g.moveTo(l,Y(15));g.lineTo(r,Y(15));g.stroke();g.setLineDash([]);pts=[];for(let a of [...DATA,ideal]){let x=X(a.trades),y=Y(a.capital);pts.push({x,y,a});if(y<t||y>b)continue;g.fillStyle=a.side==='Идеал'?'#ffe66d':a.side==='Long'?'#65daa1':'#ffad55';g.globalAlpha=.75;g.beginPath();g.arc(x,y,a.side==='Идеал'?8:4,0,7);g.fill()}g.globalAlpha=1}
el.onclick=e=>{let r=el.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top,p=[...pts].sort((a,b)=>Math.hypot(a.x-x,a.y-y)-Math.hypot(b.x-x,b.y-y))[0];if(p&&Math.hypot(p.x-x,p.y-y)<28)document.getElementById('selected').textContent=JSON.stringify(p.a)};
document.getElementById('mode').onchange=draw;window.onresize=draw;draw();const sorted=[...DATA].sort((a,b)=>b.capital-a.capital),dead=DATA.filter(a=>a.capital<.5).length;document.getElementById('overview').textContent='Лучший: '+sorted[0].side+' '+sorted[0].leverage+'×, '+(sorted[0].pyramid?'добавления':'без добавлений')+', $'+sorted[0].capital+' за '+sorted[0].trades+' сделок. Почти разорились: '+dead+' из '+DATA.length+' вариантов.';document.getElementById('tbody').innerHTML=sorted.map(a=>'<tr><td>'+a.side+'</td><td>'+a.leverage+'×</td><td>'+a.adds+'</td><td>'+a.trades+'</td><td>$'+a.capital+'</td><td>$'+a.fees+'</td><td>'+a.liquidations+'</td><td>'+a.drawdown+'%</td><td>'+(a.threshold*100).toFixed(1)+'%</td></tr>').join('');
</script></html>'''
(R/'artifacts'/'aggressive_20d.html').write_text(page.replace('__DATA__',json.dumps([{k:v for k,v in a.items() if k!='curve'} for a in results])))
print('READY',flush=True)
