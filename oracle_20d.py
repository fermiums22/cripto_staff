#!/usr/bin/env python3
"""Produce a static, hindsight-only oracle chart. No orders, bot or dashboard modifications."""
import gzip,json,datetime,pathlib,html
ROOT=pathlib.Path(__file__).resolve().parent
SYMS=['QUSDT','INITUSDT','1000PEPEUSDT']
all_data={}
for sym in SYMS:
    with gzip.open(ROOT/'data/portfolio'/f'{sym}.json.gz','rt') as f: x=json.load(f)['trade'][-1920:]
    candles=[[int(r[0]),float(r[4])] for r in x]
    # Noncausal hindsight oracle: local extrema at 3-hour neighborhood, then select profitable alternating trades
    p=[r[1] for r in candles]; n=len(p); window=12
    piv=[0]
    for i in range(window,n-window):
        chunk=p[i-window:i+window+1]
        if (p[i]==min(chunk) or p[i]==max(chunk)) and (not piv or i-piv[-1]>4): piv.append(i)
    piv.append(n-1)
    # Oracle optimal nonoverlapping long-only selection, max 20 trades, on candle close, no intra-bar execution assumption.
    # Cost 0.055% taker + 0.05% slippage each side
    cost=0.00105
    # DP with minimum 3% expected gross swing, hindsight selection; restrict to pivots for readability
    piv=sorted(set(piv))
    # Work with zigzag extrema replacing consecutive same-direction changes
    zig=[piv[0]]
    for idx in piv[1:]:
        if idx==zig[-1]:continue
        zig.append(idx)
    # Greedy post-hoc: buy at pronounced local low, sell at subsequent peak (threshold 8%)
    trades=[]; state='flat'; entry=None; j=0
    while j<len(zig)-1:
        a=zig[j]; b=zig[j+1]
        if p[b]/p[a]>1.08 and state=='flat':
            entry=a;state='long'
        if state=='long':
            if p[b]>p[entry]*1.08:
                # search for maximum until next 8% downswing; hindsight
                peak=b;k=j+1
                while k<len(zig)-1 and p[zig[k+1]]>=p[peak]*0.92:
                    k+=1
                    if p[zig[k]]>p[peak]:peak=zig[k]
                if p[peak]/p[entry]>(1+cost)/(1-cost)*1.04:
                    trades.append([entry,peak]);j=max(j,k);state='flat';entry=None
        j+=1
    # avoid overlapping / duplicates, and cap size to avoid absurd rapid repeated trades
    trades=sorted(set(tuple(z) for z in trades),key=lambda t:t[0])
    clean=[];last=-1
    for a,b in trades:
        if a>last and b>a:
            clean.append((a,b));last=b
    eq=15.; equity=[[candles[0][0],15.]];logs=[];fees=0.
    for a,b in clean:
        before=eq; entry_price=p[a]*(1+cost-0.00055); exit_price=p[b]*(1-cost+0.00055)
        # leverage 1, all equity; exchange fee 0.055%, simulated slippage 0.05% each side
        eq=eq*(1-cost)/(1+cost)*p[b]/p[a]
        fees+=before*0.00055+before*(1-cost)/(1+cost)*p[b]/p[a]*0.00055
        equity.extend([[candles[a][0],before*(1-cost)],[candles[b][0],eq]])
        logs.append(dict(buy=candles[a],sell=candles[b],net=eq-before,percent=(eq/before-1)*100))
    equity.append([candles[-1][0],eq])
    all_data[sym]=dict(candles=candles,trades=logs,equity=equity,final=eq,fee=fees,grossRange=(max(p)/min(p)-1)*100)
page=r'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Идеальная торговля · 20 дней</title>
<style>body{margin:0;background:#0d1521;color:#e6eaf2;font:15px system-ui,Arial}main{max-width:1250px;margin:auto;padding:20px}h1{font-size:26px}p,small{color:#a9b6ca}select{padding:9px;background:#162435;color:#fff;border:1px solid #33475d;border-radius:8px}.cards{display:flex;gap:12px;flex-wrap:wrap}.card{background:#162435;padding:15px;border-radius:10px;min-width:140px;flex:1}.card b{display:block;font-size:24px}.plot{width:100%;height:350px;background:#101c2c;border-radius:12px;touch-action:pan-y}section{background:#142031;padding:16px;border-radius:12px;margin-top:16px}.tablebox{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:8px;border-bottom:1px solid #314052;text-align:right}th:first-child,td:first-child{text-align:left}.green{color:#6fe3a5}.orange{color:#ffc17a}a{color:#8bcafa}</style><main>
<h1>Идеальная торговля · 20 дней</h1>
<p>Реальные 15-минутные свечи из архива Bybit. <strong class="orange">ORACLE / подглядывание в будущее:</strong> входы и выходы размечены после просмотра всей истории. Это иллюстрация потолка, не торгуемая стратегия.</p>
<select id="coin"><option>QUSDT</option><option>INITUSDT</option><option>1000PEPEUSDT</option></select>
<div class="cards"><div class="card">Старт<b>15 USDT</b></div><div class="card">Финиш<b id="final">—</b></div><div class="card">Чистый результат<b id="profit">—</b></div><div class="card">Сделки<b id="count">—</b></div><div class="card">Комиссии (оценка)<b id="fee">—</b></div></div>
<section><h3>Цена: зелёный — покупка, оранжевый — продажа</h3><canvas id="price" class="plot"></canvas></section>
<section><h3>Капитал после сделок, USDT</h3><canvas id="equity" class="plot"></canvas><small>Один актив, long-only, плечо 1×, весь доступный капитал на каждую сделку, без одновременных позиций. Вне позиции капитал постоянен.</small></section>
<section><h3>Сделки</h3><div class="tablebox"><table><thead><tr><th>№</th><th>Купили (UTC)</th><th>Купили по</th><th>Продали (UTC)</th><th>Продали по</th><th>Чистые %</th><th>Чистые USDT</th></tr></thead><tbody id="rows"></tbody></table></div></section>
<p><strong>Издержки:</strong> taker fee 0,055% + моделируемое проскальзывание 0,05% с каждой стороны, итого ~0,21% на полный оборот без funding. Для 15-минутных OHLC нет подтверждённых исполнимых котировок: используются цены закрытия свечей, а ликвидность, шаги лота, биржевые минимумы, funding и влияние сделки на рынок не воспроизведены. Фактическая прибыль может быть значительно меньше. Нет торговли и доступа к API-ключам.</p>
<a href="http://192.168.0.8:8765/">Вернуться к основной панели</a>
</main><script>const DATA=__DATA__;
const fmt=(x,d=2)=>Number(x).toFixed(d),dt=x=>new Date(x).toISOString().slice(0,16).replace('T',' ');
function draw(id, series, trades, price){let c=document.getElementById(id),w=c.clientWidth,h=c.clientHeight,dpr=devicePixelRatio||1;c.width=w*dpr;c.height=h*dpr;let g=c.getContext('2d');g.scale(dpr,dpr);g.clearRect(0,0,w,h);let left=62,right=w-16,top=20,bottom=h-37,lo=Math.min(...series.map(x=>x[1])),hi=Math.max(...series.map(x=>x[1]));if(hi===lo)hi=lo+1;let x=t=>left+(t-series[0][0])/(series.at(-1)[0]-series[0][0])*(right-left),y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top);
g.strokeStyle='#304258';g.fillStyle='#9fb1c9';g.font='12px system-ui';for(let i=0;i<=4;i++){let v=lo+(hi-lo)*i/4,py=y(v);g.beginPath();g.moveTo(left,py);g.lineTo(right,py);g.stroke();g.fillText(price?v.toPrecision(3):fmt(v,1),4,py+4)}
for(let i=0;i<=4;i++){let t=series[0][0]+(series.at(-1)[0]-series[0][0])*i/4;g.fillText(new Date(t).toISOString().slice(5,10),x(t)-15,h-13)}
g.strokeStyle=price?'#6aaafa':'#6fe3a5';g.lineWidth=1.6;g.beginPath();series.forEach((p,i)=>{i?g.lineTo(x(p[0]),y(p[1])):g.moveTo(x(p[0]),y(p[1]))});g.stroke();
if(price)trades.forEach(t=>{for(let [pt,color] of [[t.buy,'#6fe3a5'],[t.sell,'#ffc17a']]){g.fillStyle=color;g.beginPath();g.arc(x(pt[0]),y(pt[1]),4,0,Math.PI*2);g.fill();}})}
function render(){let s=DATA[document.getElementById('coin').value];document.getElementById('final').textContent=fmt(s.final)+' USDT';document.getElementById('profit').textContent=(s.final>=15?'+':'')+fmt(100*(s.final/15-1))+'%';document.getElementById('count').textContent=s.trades.length;document.getElementById('fee').textContent=fmt(s.fee)+' USDT';document.getElementById('rows').innerHTML=s.trades.map((t,i)=>'<tr><td>'+(i+1)+'</td><td>'+dt(t.buy[0])+'</td><td>'+t.buy[1]+'</td><td>'+dt(t.sell[0])+'</td><td>'+t.sell[1]+'</td><td class="green">'+fmt(t.percent)+'%</td><td>'+fmt(t.net,3)+'</td></tr>').join('');draw('price',s.candles,s.trades,true);draw('equity',s.equity,s.trades,false)}
document.getElementById('coin').onchange=render;window.onresize=render;render();</script></html>'''
out=ROOT/'artifacts'/'oracle_20d.html'
out.write_text(page.replace('__DATA__',json.dumps(all_data,separators=(',',':'))),encoding='utf8')
for s,a in all_data.items():print(s,'trades',len(a['trades']),'final',round(a['final'],2),'fees',round(a['fee'],3))
print('CREATED',out)
