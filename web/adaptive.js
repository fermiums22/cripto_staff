'use strict';
const $=id=>document.getElementById(id);
const money=v=>Number.isFinite(v)?'$'+v.toFixed(3):'—';
const percent=v=>Number.isFinite(v)?v.toFixed(2)+'%':'—';
const date=v=>v?new Date(v).toISOString().replace('T',' ').slice(0,19):'—';
const text=(id,value)=>{$(id).textContent=value;};
let lastData=null;
function table(id,rows,selected=-1){
  const target=$(id);target.replaceChildren();
  rows.forEach((values,i)=>{const row=document.createElement('tr');if(i===selected)row.className='selected';values.forEach(value=>{const td=document.createElement('td');td.textContent=value;row.append(td);});target.append(row);});
}
function list(id,rows){$(id).replaceChildren(...rows.map(v=>{const li=document.createElement('li');li.textContent=v;return li;}));}
function chart(id,series){
  const canvas=$(id),rect=canvas.getBoundingClientRect(),ratio=window.devicePixelRatio||1;
  canvas.width=Math.round(rect.width*ratio);canvas.height=Math.round(rect.height*ratio);
  const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);
  const points=series.flatMap(s=>s.points||[]).filter(p=>Number.isFinite(p[0])&&Number.isFinite(p[1]));
  if(!points.length){ctx.fillStyle='#94a6bb';ctx.fillText('Ожидание реальных наблюдений…',20,40);return;}
  let minX=Infinity,maxX=-Infinity,minY=15,maxY=15;
  for(const [x,y] of points){minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);}
  const pad=Math.max(.05,(maxY-minY)*.08);minY-=pad;maxY+=pad;
  const width=rect.width-76,height=rect.height-42;
  const x=v=>55+(v-minX)/(maxX-minX||1)*width,y=v=>12+height-(v-minY)/(maxY-minY)*height;
  ctx.font='11px system-ui';ctx.lineWidth=1;
  for(let i=0;i<4;i++){const v=minY+(maxY-minY)*i/3;ctx.strokeStyle='#293647';ctx.beginPath();ctx.moveTo(55,y(v));ctx.lineTo(rect.width-20,y(v));ctx.stroke();ctx.fillStyle='#94a6bb';ctx.fillText('$'+v.toFixed(2),2,y(v)+4);}
  ctx.setLineDash([4,4]);ctx.strokeStyle='#94a6bb';ctx.beginPath();ctx.moveTo(55,y(15));ctx.lineTo(rect.width-20,y(15));ctx.stroke();ctx.setLineDash([]);
  for(const s of series){if(!s.points?.length)continue;ctx.strokeStyle=s.color;ctx.lineWidth=2;ctx.beginPath();s.points.forEach((p,i)=>i?ctx.lineTo(x(p[0]),y(p[1])):ctx.moveTo(x(p[0]),y(p[1])));ctx.stroke();if(s.points.length===1){ctx.fillStyle=s.color;ctx.beginPath();ctx.arc(x(s.points[0][0]),y(s.points[0][1]),3,0,2*Math.PI);ctx.fill();}}
  ctx.fillStyle='#94a6bb';ctx.fillText(date(minX).slice(0,16),55,rect.height-4);ctx.textAlign='right';ctx.fillText(date(maxX).slice(0,16),rect.width-20,rect.height-4);
}
function render(data){
  lastData=data;const live=data.live,w=live?.wallet,m=live?.metrics,r=data.research;
  const age=live?.updated_ms?Math.max(0,(Date.now()-live.updated_ms)/1000):null;
  const errors=[];if(live?.last_error)errors.push('Ошибка сбора: '+live.last_error);if(age===null||age>120)errors.push('Живые данные ещё не готовы или устарели.');
  $('error').hidden=!errors.length;text('error',errors.join(' '));
  text('health',live?.live_gate?'PAPER · контроль сигналов':'Сбор данных · входы заблокированы отбором');
  text('freshness',age===null?'Нет свежего цикла':'Цикл '+Math.round(age)+' с назад · '+date(live.quote_ms)+' UTC');
  text('equity',money(live?.equity));const p=w?.position;
  text('position',p?p.symbol+' '+(p.side>0?'LONG':'SHORT'):'Нет позиции');
  text('exposure',p?'Количество '+p.qty+' · вход '+p.entry:'Доступно '+money(w?.cash)+' · плечо ≤1×');
  text('fees',money(m?.fees));text('funding','Funding: '+money(m?.funding));
  text('trades',m?String(m.trades):'—');text('drawdown','Просадка: '+percent(w?.max_drawdown_pct));
  text('decision',w?.decision||'Сервис начинает сбор данных.');
  const c=live?.candidate;text('candidate',c?'Кандидат: '+c.symbol+' '+(c.side>0?'LONG':'SHORT')+' · '+c.reason:'Нет подходящего кандидата после фильтра издержек.');
  text('gate',(live?.paused?'Глобальная пауза. ':'')+(live?.live_gate?'Допуск: train и validation положительны.':'Нет допуска: нужна положительная train и validation, результат теста не меняет допуск.')+' Наблюдаемых монет: '+(live?.observed_symbols||0));
  const q=p?live?.prices?.[p.symbol]:c?live?.prices?.[c.symbol]:null;
  text('quote',q?'Bid '+q.bid+' / Ask '+q.ask+' / Mark '+q.mark+' · spread '+percent(q.spread*100):'Ожидание котировки выбранной монеты.');
  chart('liveChart',[{points:w?.curve||[],color:'#55d5b3'}]);
  table('liveTrades',(w?.trades||[]).slice(-30).reverse().map(t=>[date(t.closed_ms),t.symbol,t.side>0?'LONG':'SHORT',money(t.gross),money(t.fees),money(t.funding),money(t.net),t.exit_reason]));
  if(!r)return;
  const protocol=r.protocol; text('selection','Зафиксирован: '+(protocol.selected?.id||'CASH')+' · '+protocol.selection);
  text('split','Train '+protocol.train.join(' → ')+' | Validation '+protocol.validation.join(' → ')+' | Test '+protocol.test.join(' → '));
  const labels={realistic:'Базовый',optimistic:'Оптимистичный',severe:'Тяжёлый стресс'},colors={realistic:'#55d5b3',optimistic:'#7ba8ff',severe:'#ff8a91'};
  chart('historyChart',Object.entries(r.scenarios).map(([key,v])=>({points:v.curve,color:colors[key]})));
  table('scenarios',Object.entries(r.scenarios).map(([key,v])=>[labels[key],money(v.capital),money(v.gross),money(v.fees),money(v.funding),money(v.net),percent(v.max_drawdown_pct),v.trades,v.liquidations,[30,100,2000].map(n=>v.milestones[n]?'да':'нет').join(' / ')]));
  text('costs',protocol.fee_note+' Базовое проскальзывание + полуспред: 0,06% за сторону; стресс: 0,30%, taker 0,15%.');
  const base=r.scenarios.realistic;text('excursions',base?'Средние MFE '+percent(base.mfe_mean_pct)+' / MAE '+percent(base.mae_mean_pct)+'. Только полностью удержанные свечи; неоднозначная свеча выхода исключена. Отказы: '+JSON.stringify(base.rejected):'Нет допущенного исторического кандидата.');
  const leaders=[...r.leaderboard].sort((a,b)=>b.validation.net-a.validation.net);
  table('leaderboard',leaders.map(v=>[v.id,money(v.train.net),money(v.validation.net),percent(v.validation.max_drawdown_pct),v.validation.trades]),leaders.findIndex(v=>v.id===protocol.selected?.id));
  table('ablations',r.ablations.map(v=>[v.id,money(v.result.net),percent(v.result.max_drawdown_pct),v.result.trades]));
  table('leverage',r.leverage_controls.map(v=>[v.leverage+'×'+(v.pyramid?' + пирамида':''),money(v.result.capital),percent(v.result.max_drawdown_pct),v.result.liquidations]));
  list('hypotheses',r.hypotheses);list('limitations',r.inventory.limitations);
  table('inventory',[...r.inventory.fifteen_minute,...r.inventory.minute,...r.inventory.cached_linear].map(v=>[v.symbol+' / '+(v.kind||v.file),v.start_utc,v.end_utc,v.bars,v.gaps]).concat(Object.entries(r.inventory.stream).map(([s,v])=>[s+' / stream',v.start_utc,v.end_utc,v.messages,Math.round(v.session_gap_ms/1000)+' s между сессиями'])));
}
async function refresh(){try{const response=await fetch('/api/adaptive',{cache:'no-store'});if(!response.ok)throw Error('HTTP '+response.status);render(await response.json());}catch(error){$('error').hidden=false;text('error','Данные временно недоступны: '+error.message);}finally{setTimeout(refresh,15000);}}
window.addEventListener('resize',()=>{if(lastData)render(lastData);});refresh();
