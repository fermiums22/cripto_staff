const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date=t=>new Intl.DateTimeFormat('ru',{timeZone:'Europe/Minsk',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(t));
const money=n=>Number(n).toLocaleString('ru',{minimumFractionDigits:2,maximumFractionDigits:4});
const pct=n=>(n>0?'+':'')+Number(n).toFixed(2)+'%';
const reasons={below_threshold:'Оценка ниже порога — ждём',stale_signal:'Ждём следующую закрытую свечу',data_gap:'Пропуск данных — вход запрещён',paused:'Пауза новых входов',position_open:'Уже есть открытая позиция',already_processed:'Эта свеча уже обработана',minimum_order:'Недостаточно суммы для минимального ордера',paper_entry:'Открыта виртуальная позиция',eligible:'Сигнал проверяется'};
let current=null, busy=false;
function chart(id,series,{base=null,markers=[]}={}){
 const canvas=$(id),dpr=window.devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;
 canvas.width=w*dpr;canvas.height=h*dpr;const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);
 const valid=series.map(s=>({...s,points:s.points.filter(p=>Number.isFinite(p[0])&&Number.isFinite(p[1]))}));
 const all=valid.flatMap(s=>s.points);ctx.font='11px system-ui';ctx.fillStyle='#94a6bb';
 if(!all.length){ctx.fillText('Пока нет наблюдений за выбранный период',20,60);canvas.onmousemove=null;return;}
 let minT=Math.min(...all.map(p=>p[0])),maxT=Math.max(...all.map(p=>p[0]));if(maxT===minT)maxT+=60000;
 let min=Math.min(...all.map(p=>p[1]),...(base===null?[]:[base])),max=Math.max(...all.map(p=>p[1]),...(base===null?[]:[base]));
 let pad=(max-min)*.12||Math.max(Math.abs(min)*.001,.01);min-=pad;max+=pad;
 const left=68,right=12,top=12,bottom=32,x=t=>left+(t-minT)/(maxT-minT)*(w-left-right),y=v=>top+(max-v)/(max-min)*(h-top-bottom);
 ctx.lineWidth=1;for(let i=0;i<5;i++){let v=min+(max-min)*i/4;ctx.strokeStyle='#263344';ctx.beginPath();ctx.moveTo(left,y(v));ctx.lineTo(w-right,y(v));ctx.stroke();ctx.fillStyle='#94a6bb';ctx.fillText(money(v),2,y(v)+4);}
 ctx.fillText(date(minT),left,h-8);ctx.textAlign='right';ctx.fillText(date(maxT),w-right,h-8);ctx.textAlign='left';
 if(base!==null){ctx.setLineDash([4,4]);ctx.strokeStyle='#94a6bb';ctx.beginPath();ctx.moveTo(left,y(base));ctx.lineTo(w-right,y(base));ctx.stroke();ctx.setLineDash([]);}
 for(const s of valid){ctx.strokeStyle=s.color;ctx.lineWidth=2;ctx.beginPath();s.points.forEach((p,i)=>i?ctx.lineTo(x(p[0]),y(p[1])):ctx.moveTo(x(p[0]),y(p[1])));ctx.stroke();if(s.points.length===1){ctx.fillStyle=s.color;ctx.beginPath();ctx.arc(x(s.points[0][0]),y(s.points[0][1]),3,0,7);ctx.fill();}}
 for(const m of markers){if(m.ts<minT||m.ts>maxT)continue;ctx.fillStyle=m.kind==='paper_entry'?'#55d5b3':'#ff8a91';ctx.beginPath();ctx.arc(x(m.ts),y(m.price),4,0,7);ctx.fill();}
 canvas.onmousemove=e=>{if(id!=='priceChart')return;let t=minT+(e.offsetX-left)/(w-left-right)*(maxT-minT);const points=valid[0].points;if(!points.length)return;const nearest=points.reduce((a,b)=>Math.abs(b[0]-t)<Math.abs(a[0]-t)?b:a);$('priceHint').textContent=date(nearest[0])+' · '+money(nearest[1])+' USDT';};
}
function render(){if(!current)return;const d=current,s=d.status,age=Math.max(0,Math.round((Date.now()-(s.heartbeat_ms||0))/1000));
 if(d.sourced_research){const r=d.sourced_research,rows=Object.entries(r.candidates);$('sourceRows').innerHTML=rows.map(([k,v])=>`<tr><td>${esc(v.name)}</td><td>${pct(v.validation.return_pct)}</td><td>${pct(v.test.return_pct)}</td><td>${pct(v.stress.return_pct)}</td><td>${v.test.trades} / ${v.test.wins}</td></tr>`).join('');chart('sourceChart',rows.map(([k,v],i)=>({points:v.test.curve,color:['#55d5b3','#7ba8ff'][i]})),{base:15});$('sourceNote').textContent='Проверка: '+date(r.split_ms)+' — '+date(r.end_ms)+'. Зелёный — BB; синий — MACD+BB. Собственная long-only адаптация входов; не результат оригинального Hummingbot. История уже изучалась.';}
 const wr=d.waiting_research;
 if(wr){const rows=Object.entries(wr.candidates),colors=['#55d5b3','#7ba8ff','#bd9bff','#ffca77','#ff8a91','#a7e887'];
 $('waitingNote').textContent='Первые 20 дней — выбор; последние 10 — проверка. '+(wr.passes_screen?'Первичный фильтр пройден; live-прибыль не доказана.':'Кандидат не прошёл фильтр допуска.')+' Выбран по первым 20 дням: '+(wr.selected||'нет: мало сделок')+'. Spot long, без плеча. История ранее использовалась; это не нетронутый тест.';
 $('waitingRows').innerHTML=rows.map(([k,r])=>`<tr><td>${esc(r.name)} · TP ${pct(r.tp*100)} / SL ${pct(r.sl*100)}</td><td>${pct(r.validation.return_pct)}</td><td>${pct(r.test.return_pct)}</td><td>${pct(r.stress.return_pct)}</td><td>${r.test.trades} / ${r.test.wins}</td><td>${r.test.mean_hold_seconds==null?'—':(r.test.mean_hold_seconds/60).toFixed(1)+' мин'}</td></tr>`).join('');
 chart('waitingChart',rows.map(([k,r],i)=>({points:r.test.curve,color:colors[i]})),{base:15});
 $('waitingLegend').textContent=rows.map(([k,r],i)=>['Зелёный','Синий','Фиолетовый','Жёлтый','Красный','Салатовый'][i]+' — '+r.name+' TP '+pct(r.tp*100)).join(' · ');}
 const bt=d.arena_backtest,bc=['#55d5b3','#7ba8ff','#ffca77'];
 if(bt){const rows=Object.entries(bt.results.base);$('arenaBacktestNote').textContent=date(bt.start_ms)+' — '+date(bt.end_ms)+' · Минутная оценка, не точный повтор live. Комиссия 0,1% и проскальзывание 0,05% за сторону; спред: база 0,02%, стресс 0,06%. Каждой стратегии $15, остановка при потере 20%. История уже использовалась в исследованиях.';
 $('arenaBacktestRows').innerHTML=rows.map(([k,r])=>`<tr><td>${esc(r.name)}</td><td>${pct(r.return_pct)}</td><td>${pct(bt.results.wide_spread[k].return_pct)}</td><td>${r.trades} / ${r.wins}</td><td>${pct(r.max_drawdown_pct)}</td><td>${r.loss_limit?'Лимит убытка':'Период завершён'}</td></tr>`).join('');
 chart('arenaBacktestChart',rows.map(([k,r],i)=>({points:r.curve,color:bc[i]})),{base:15});
 $('arenaBacktestLegend').textContent=rows.map(([k,r],i)=>['Зелёный','Синий','Жёлтый'][i]+' — '+r.name).join(' · ');}
 const arena=d.arena||[],as=d.arena_status,arenaColors=['#55d5b3','#7ba8ff','#bd9bff','#ffca77','#ff8a91','#a7e887','#ffffff','#ff8c42','#41d9ef','#e879f9','#c4a484'];
 const arenaReasons={retired:'Отключён: не прошёл проверку',waiting_signal:'Ждёт сигнал',waiting_cost_signal:'Ждёт сильное движение · фильтр издержек',stale_quote:'Нет свежей цены',loss_limit:'Лимит убытка',cooldown:'Пауза между входами',minimum_order:'Минимальный ордер',insufficient_top_liquidity:'Недостаточная ликвидность',warmup:'Сбор котировок',paused:'Пауза'};
 $('arenaHealth').textContent=as?'Цикл '+Math.max(0,Math.round((Date.now()-as.heartbeat_ms)/1000))+' с назад'+(as.last_error?' · ошибка '+as.last_error:''):'Ожидаем первый цикл';
 $('arenaRows').innerHTML=arena.map((a,i)=>`<tr><td>${esc(a.name)}</td><td>${money(a.equity)}</td><td class="${a.equity<15?'negative':'positive'}">${money(a.equity-15)}</td><td>${a.trades}</td><td>${a.trades?(a.holding_seconds/a.trades).toFixed(0)+' с':'—'}</td><td>${a.position?esc(a.position.symbol)+' · '+Math.max(0,Math.round((Date.now()-a.position.opened_ms)/1000))+' с':esc(arenaReasons[a.reason]||a.reason)}</td></tr>`).join('');
 chart('arenaChart',arena.map((a,i)=>({points:a.curve||[],color:arenaColors[i%arenaColors.length]})),{base:15});
 $('arenaLegend').textContent=arena.map((a,i)=>['Зелёный','Синий','Фиолетовый','Жёлтый','Красный','Салатовый','Белый','Оранжевый','Голубой','Розовый','Коричневый'][i%arenaColors.length]+' — '+a.name).join(' · ');
 const job=d.research_job,search=d.search_result,news=d.market_context;
 if(job){const stages={download:'Скачивание реальной минутной истории',training:'Обучение на GPU',completed:'Поиск завершён',failed:'Ошибка поиска'};$('job').textContent=(stages[job.stage]||job.stage)+' · '+(job.symbol||'')+(job.candles?' · '+job.candles.toLocaleString('ru')+' свечей':'')+(job.total?' · '+job.completed+'/'+job.total+' моделей':'')+' · '+date(job.updated_ms)+(job.error?' · '+job.error:'');}
 if(search){const trades=Object.values(search.test).reduce((a,b)=>a+b.trades,0);$('searchResult').textContent='Выбрано на validation: '+search.selected+'. Средний результат отдельного теста: '+pct(search.test_mean_pct)+', с двойным проскальзыванием: '+pct(search.stress_mean_pct)+'. Сделок: '+trades+'. '+(search.passes_initial_screen?'Первичный фильтр пройден; нужна дальнейшая проверка.':'Кандидат отклонён первичным фильтром.')+' Рабочая модель не изменена.';$('searchDetails').innerHTML=Object.entries(search.test).map(([symbol,r])=>`<p>${esc(symbol)} · ${pct(r.return_pct)} · ${r.trades_per_day.toFixed(2)} сделок/день · удержание ${r.mean_hold_minutes==null?'—':r.mean_hold_minutes.toFixed(1)} мин</p>`).join('')+'<p class="hint">Отдельные тестовые счета по 15 USDT; это не результат одного общего портфеля. Минутные свечи не проверяют исполнение за миллисекунды.</p>';}
 if(news){$('newsStatus').textContent='Обновлено '+date(news.updated_ms)+' · '+Object.entries(news.sources).map(([n,v])=>n+': '+(v.ok?'OK':'ошибка')).join(' · ');$('news').innerHTML=news.items.slice(0,8).map(n=>`<p><a href="${esc(n.url)}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a> <small>${esc(n.source)} · ${esc(n.category)} · получено ${date(n.first_seen_ms)}</small></p>`).join('');}
 $('health').textContent=age>120?'● Нет свежего цикла':s.paused?'● Пауза новых входов':'● Бот работает · проверяет рынок';$('updated').textContent='Цикл '+age+' с назад';
 $('equity').textContent=money(s.equity_usdt??15)+' USDT';$('pnl').textContent=(s.pnl_usdt>0?'+':'')+money(s.pnl_usdt??0)+' USDT';$('pnl').className=s.pnl_usdt<0?'negative':'positive';
 $('position').textContent=s.portfolio?.position?.symbol||'Нет позиции';$('bars').textContent=Object.values(d.counts).reduce((a,b)=>a+b,0).toLocaleString('ru');
 $('error').hidden=!s.last_error;if(s.last_error)$('error').textContent='Ошибка цикла: '+s.last_error;
 $('decisions').innerHTML=Object.entries(d.models).map(([symbol,m])=>{const q=s.decisions?.[symbol],p=q?.probability;return `<article><h3>${esc(symbol)}<span>${p==null?'—':(p*100).toFixed(1)+'%'}</span></h3><progress max="1" value="${p??0}"></progress><p>${esc(s.paused?'Пауза новых входов':reasons[q?.reason]||'Ожидаем диагностику')} · порог 60%</p></article>`}).join('');
 const marks=d.events.filter(e=>e.symbol===d.symbol&&['paper_entry','paper_exit'].includes(e.kind)).map(e=>({...e,price:e.kind==='paper_entry'?e.entry:e.proceeds/(e.qty*(1-.001))}));
 chart('priceChart',[{points:d.candles.map(b=>[b[0]+300000,b[4]]),color:'#55d5b3'}],{markers:marks});
 chart('equityChart',[{points:d.equity,color:'#7ba8ff'}],{base:15});
 const c=d.comparison;
 if(c){$('strategies').innerHTML=Object.entries(c.strategies).map(([id,r])=>`<tr><td>${esc(r.name)}${id===c.selected_on_validation?' · кандидат':''}</td><td class="${r.validation_mean_pct<0?'negative':'positive'}">${pct(r.validation_mean_pct)}</td><td class="${r.test_mean_pct<0?'negative':'positive'}">${pct(r.test_mean_pct)}</td><td>${r.test_trades}</td></tr>`).join('');
 const prev=$('strategy').value;$('strategy').innerHTML=Object.entries(c.strategies).map(([id,r])=>`<option value="${esc(id)}">${esc(r.name)}</option>`).join('');if(c.strategies[prev])$('strategy').value=prev;
 const chosen=c.strategies[c.selected_on_validation];$('researchNote').textContent='Тест: '+date(c.test_start_ms)+' — '+date(c.test_end_ms)+'. Средние результаты по трём монетам. '+(chosen.passes_initial_screen?'Кандидат прошёл первичный численный фильтр; нужны дальнейшие проверки.':'Доходность не подтверждена: кандидат не прошёл первичный фильтр.');renderResearch();
 }else{$('strategies').innerHTML='<tr><td colspan="4">Исследование запускается…</td></tr>';}
 const names={paper_entry:'Вход',paper_exit:'Выход',error:'Ошибка',skip_minimum_order:'Минимальный ордер'};
 $('events').innerHTML=d.events.length?d.events.map(e=>`<tr><td>${date(e.ts)}</td><td>${esc(names[e.kind]||e.kind)} · ${esc(e.strategy_name||'Базовая ML')}</td><td>${esc(e.symbol||'—')}</td><td>${e.pnl_usdt!=null?money(e.pnl_usdt)+' USDT':esc(e.reason||'—')}</td></tr>`).join(''):'<tr><td colspan="4">Сделок ещё нет. Бот ждёт подходящего сигнала; принудительные входы не создаются.</td></tr>';
}
function renderResearch(){const c=current?.comparison,r=c?.strategies[$('strategy').value]?.symbols[$('symbol').value]?.test;$('curveTitle').textContent='Тест стратегии · '+$('symbol').value;chart('researchChart',[{points:r?.curve||[],color:'#bd9bff'}],{base:15});}
async function refresh(){if(busy)return;busy=true;try{const response=await fetch('/api/snapshot?'+new URLSearchParams({symbol:$('symbol').value,hours:$('hours').value}),{cache:'no-store'});if(!response.ok)throw new Error('HTTP '+response.status);current=await response.json();render();}catch(e){$('error').hidden=false;$('error').textContent='Панель не получает данные: '+e.message;$('health').textContent='● Соединение потеряно';}finally{busy=false;}}
$('symbol').onchange=refresh;$('hours').onchange=refresh;$('strategy').onchange=renderResearch;window.addEventListener('resize',render);refresh();setInterval(refresh,5000);
