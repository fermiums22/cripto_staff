import gzip,json,pathlib
import portfolio_market
R=pathlib.Path(__file__).resolve().parent
raw=json.load(gzip.open(R/'data/portfolio/QUSDT.json.gz'))['trade'][-1920:]
bars=portfolio_market.candles('QUSDT','kline',raw[0][0],raw[-1][0]+14*60000,interval=1)
assert len(bars)==28800
fee=.001; slip=.0005
results=[]
for side in (1,-1):
 for lev in (1,2,3,5,8):
  for threshold in (.008,.015,.03,.05):
   for grow in (False,True):
    for hold in (1,3,6):
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
       if grow and p['adds']<3 and i-p['lastadd']>=3 and gain>(.008+.008*p['adds']) and cash>1:
        alloc=cash*.7;fill=nextopen*(1+side*slip);nom=alloc*lev;newfee=nom*fee
        if alloc+newfee<=cash:
         oldqty=p['qty'];p['qty']+=nom/fill;p['entry']=(oldqty*p['entry']+(nom/fill)*fill)/p['qty'];p['margin']+=alloc
         cash-=alloc+newfee;fees+=newfee;p['adds']+=1;p['lastadd']=i+1;adds+=1
       age=i-p['start']
       weakening=age>=2 and side*(close/bars[i-2][4]-1)<-.003 and gain>.004
       trail=side*(close/p['best']-1)<-(.017*hold)
       stop=gain<-(.025*hold)
       if (weakening and hold==1) or trail or stop or age>=90*hold:
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
     results.append(dict(side='Long' if side==1 else 'Short',leverage=lev,pyramid=grow,threshold=threshold,capital=round(cash,4),trades=trades,fees=round(fees,4),liquidations=liqs,adds=adds,drawdown=round(100*dd,2),hold=hold,curve=curve))
     print(side,lev,threshold,grow,hold,round(cash,2),trades,liqs,flush=True)

old=R/'artifacts'/'aggressive_20d.html'
import re
page=old.read_text()
page=re.sub(r'const DATA=.*?,ideal=', 'const DATA='+json.dumps([{k:v for k,v in r.items() if k!='curve'} for r in results])+',ideal=',page,flags=re.S)
page=page.replace('80 экспериментов','240 экспериментов')
page=page.replace('с плечом 1–10×','с плечом 1–8× и разными временами удержания')
page=page.replace('Лучшие и опасные сценарии','Лучшие и опасные сценарии · регулируемый выход')
page=page.replace('<th>Плечо</th><th>Добавления</th>', '<th>Плечо</th><th>Выход ×</th><th>Добавления</th>')
page=page.replace("a.leverage+'×</td><td>'+a.adds", "a.leverage+'×</td><td>'+a.hold+'×</td><td>'+a.adds")
page=page.replace('Тест №3 · Испытание импульса','Тест №3 · Охота за волной')
page=page.replace('Лучшие и опасные сценарии · регулируемый выход','Лучшие и опасные сценарии · регулируемый выход')
page=page.replace('Победители используют высокий порог:', 'В предыдущем наборе победители использовали высокий порог:')
# Existing survivor summary and histogram adapt dynamically
page=page.replace("const levers=[1,2,3,5,10]","const levers=[1,2,3,5,8]")
page=page.replace('все 80 вариантов','все 240 вариантов')
(R/'artifacts'/'wave_hunt_20d.html').write_text(page)
(R/'artifacts'/'wave_hunt_20d.json').write_text(json.dumps(results))
print('BEST',sorted(({k:v for k,v in r.items() if k!='curve'} for r in results),key=lambda r:r['capital'],reverse=True)[:5],flush=True)
print('READY',flush=True)
