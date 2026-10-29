"""One shared $15 account; isolated-margin OHLC approximation, no order API."""
from decimal import Decimal,ROUND_DOWN,ROUND_CEILING,ROUND_FLOOR
import math
import numpy as np


def quantity(budget,price,leverage,fee,lot):
    step=Decimal(lot['qtyStep']);q=(Decimal(str(budget))/Decimal(str(price*(1/leverage+fee)))/step).to_integral_value(rounding=ROUND_DOWN)*step
    q=min(q,Decimal(lot.get('maxMktOrderQty') or lot.get('maxOrderQty') or str(q)))
    q=(q/step).to_integral_value(rounding=ROUND_DOWN)*step
    if q<Decimal(lot['minOrderQty']) or q*Decimal(str(price))<Decimal(lot['minNotionalValue']):return 0.
    return float(q)


def fill(price,side,friction,instrument):
    tick=Decimal(instrument['priceFilter']['tickSize'])
    return float((Decimal(str(price*(1+side*friction)))/tick).to_integral_value(
        rounding=ROUND_CEILING if side>0 else ROUND_FLOOR)*tick)


def simulate(market,predictions,start,end,mode='multi',leverage=1,fee=.001,
             threshold=.006,friction=.0006,allocation=.9,max_positions=3,hold_bars=16):
    symbols=sorted(market);clock=market[symbols[0]]['trade'];cash=15.;positions={};records=[]
    curve=[[clock[start][0],15.]];allocations=[];peak=15.;dd=0.;peak_ms=clock[start][0];drawdown_event=None
    rejected=dict(minimum_order=0,correlated=0,liquidity=0,risk_limit=0)
    rates={s:{int(r['fundingRateTimestamp']):float(r['fundingRate']) for r in d['funding']} for s,d in market.items()}
    returns={s:np.diff(np.log(np.array([r[4] for r in d['trade']]))) for s,d in market.items()}
    high_water={str(v):None for v in (100,500,1000,40000)};liquidations=0;max_open=0
    def close(s,price,i,reason):
        nonlocal cash,liquidations
        p=positions.pop(s);exit_price=fill(price,-p['side'],friction,market[s]['instrument'])
        gross=p['side']*p['qty']*(exit_price-p['entry']);exit_fee=p['qty']*exit_price*fee
        returned=max(0.,p['margin']+gross-exit_fee)
        # Isolated bankruptcy cap is explicit; not an insurance-fund reconstruction.
        adjustment=returned-(p['margin']+gross-exit_fee)
        cash+=returned
        net=returned-p['initial_margin']-p['entry_fee']+p['funding_cash']
        records.append(dict(symbol=s,side=p['side'],entry_ms=clock[p['opened']][0],exit_ms=clock[i][0]+(900000 if reason=='boundary' else 0),
            qty=p['qty'],entry=p['entry'],exit=exit_price,leverage=leverage,
            gross=gross,fees=p['entry_fee']+exit_fee,funding=p['funding'],
            bankruptcy_adjustment=adjustment,net=net,reason=reason,selection=p['reason']))
        if reason=='liquidation_proxy':liquidations+=1
    def value(i,adverse=False):
        total=cash
        for s,p in positions.items():
            mark=market[s]['mark'][i]
            price=mark[3 if p['side']==1 else 2] if adverse else mark[4]
            exit_price=fill(price,-p['side'],friction,market[s]['instrument'])
            total+=max(0,p['margin']+p['qty']*p['side']*(exit_price-p['entry'])-p['qty']*exit_price*fee)
        return total
    def liquidate(s,price,i):
        p=positions[s];risk=market[s]['risk']
        maintenance=max(0,p['qty']*price*float(risk['maintenanceMargin'])-float(risk.get('mmDeduction') or 0))
        equity=p['margin']+p['qty']*p['side']*(price-p['entry'])
        if equity<=maintenance+p['qty']*price*fee:close(s,price,i,'liquidation_proxy')
    def observe_drawdown(equity,i,kind):
        nonlocal dd,drawdown_event
        decline=100*(1-equity/peak)
        if decline>dd:
            dd=decline
            drawdown_event=dict(bar_ms=clock[i][0],kind=kind,peak=peak,peak_ms=peak_ms,
                equity=equity,cash=cash,positions=[dict(symbol=s,**p) for s,p in positions.items()])
    for i in range(start+1,end):
        # Apply all settlements inside a bar before discretionary actions; rates
        # at non-open timestamps are applied at this bar's open conservatively.
        for s in list(positions):
            p=positions[s];mark=market[s]['mark'][i]
            amount=-p['side']*p['qty']*mark[1]*rates[s].get(clock[i][0],0.)
            p['funding']+=amount
            from_cash=max(amount,-cash);cash+=from_cash;p['funding_cash']+=from_cash
            p['margin']+=amount-from_cash
            liquidate(s,mark[1],i)
        for s in list(positions):
            p=positions[s];signal=float(predictions[s][i-1]);age=i-p['opened']
            if age>=hold_bars or (age>=4 and p['side']*signal<-threshold):
                close(s,market[s]['trade'][i][1],i,'timeout' if age>=hold_bars else 'opposite_signal')
        # Distribute the remaining shared wallet; never grant a new symbol $15.
        if i%4==0 and cash>0:
            candidates=[]
            for s in symbols:
                if s in positions or (mode=='single' and s!='SOLUSDT'):continue
                d=market[s];hist=d['trade'][max(0,i-96):i];signal=float(predictions[s][i-1])
                if not math.isfinite(signal) or abs(signal)<threshold:continue
                # These liquidity and pump checks use ONLY bars available at decision time.
                turnover=sum(b[6] for b in hist);recent=d['trade'][i-1][4]/d['trade'][max(0,i-5)][4]-1
                if turnover<3000000 or abs(recent)>.05:
                    rejected['liquidity']+=1;continue
                vol=float(np.std(returns[s][max(0,i-97):i-1]))
                candidates.append((abs(signal)/(vol+.001),s,1 if signal>0 else -1,signal,vol))
            candidates.sort(reverse=True);chosen=[]
            limit=max_positions if mode=='multi' else 1
            for score,s,side,signal,vol in candidates:
                if len(positions)+len(chosen)>=limit:break
                d=market[s];price=fill(d['trade'][i][1],side,friction,d['instrument'])
                if not quantity(cash*allocation,price,leverage,fee,d['instrument']['lotSizeFilter']):
                    rejected['minimum_order']+=1;continue
                others=[(other,p['side']) for other,p in positions.items()]+[(v[1],v[2]) for v in chosen]
                correlated=False
                for other,other_side in others:
                    a=returns[s][max(0,i-97):i-1];b=returns[other][max(0,i-97):i-1]
                    corr=float(np.corrcoef(a,b)[0,1]) if np.std(a)>0 and np.std(b)>0 else 1.
                    if corr*side*other_side>.75:correlated=True;break
                if correlated:rejected['correlated']+=1;continue
                chosen.append((score,s,side,signal,vol))
            budget=cash*allocation
            while len(chosen)>1:
                total_score=sum(v[0] for v in chosen)
                feasible=all(quantity(budget*v[0]/total_score,
                    fill(market[v[1]]['trade'][i][1],v[2],friction,market[v[1]]['instrument']),
                    leverage,fee,market[v[1]]['instrument']['lotSizeFilter']) for v in chosen)
                if feasible:break
                chosen.pop();rejected['minimum_order']+=1
            total_score=sum(v[0] for v in chosen)
            for score,s,side,signal,vol in chosen:
                d=market[s];price=fill(d['trade'][i][1],side,friction,d['instrument'])
                part=budget*score/total_score
                q=quantity(part,price,leverage,fee,d['instrument']['lotSizeFilter'])
                if not q:rejected['minimum_order']+=1;continue
                risk=d['risk'];max_leverage=min(float(d['instrument']['leverageFilter']['maxLeverage']),float(risk.get('maxLeverage') or 100))
                if leverage>max_leverage or q*price>float(risk['riskLimitValue']):rejected['risk_limit']+=1;continue
                margin=q*price/leverage;entry_fee=q*price*fee
                if margin+entry_fee>cash+1e-9:raise AssertionError('Overspent shared capital')
                cash-=margin+entry_fee
                reason=f'Прогноз {signal:+.4%}; оценка с учётом риска {score:.3f}; прошлая волатильность {vol:.4%}'
                positions[s]=dict(qty=q,side=side,entry=price,margin=margin,initial_margin=margin,
                    entry_fee=entry_fee,opened=i,funding=0.,funding_cash=0.,reason=reason)
        max_open=max(max_open,len(positions))
        observe_drawdown(value(i,True),i,'adverse_mark_envelope')
        for s in list(positions):
            p=positions[s];liquidate(s,market[s]['mark'][i][3 if p['side']==1 else 2],i)
        equity=value(i)
        if equity>peak:peak=equity;peak_ms=clock[i][0]
        observe_drawdown(equity,i,'mark_close');curve.append([clock[i][0]+900000,equity])
        for target in high_water:
            if equity>=int(target) and high_water[target] is None:high_water[target]=clock[i][0]+900000
        if i%4==0:
            allocations.append(dict(ts=clock[i][0],cash=cash,equity=equity,positions=[dict(symbol=s,
                margin=p['margin'],notional=p['qty']*market[s]['mark'][i][4],side=p['side'],reason=p['reason'],
                unrealized=p['side']*p['qty']*(market[s]['mark'][i][4]-p['entry'])) for s,p in positions.items()]))
        if cash<=1e-8 and not positions:break
    terminal_positions=allocations[-1] if allocations else dict(positions=[],cash=cash)
    for s in list(positions):close(s,market[s]['trade'][end-1][4],end-1,'boundary')
    curve.append([clock[end-1][0]+900000,cash]);observe_drawdown(cash,end-1,'terminal')
    assert abs(cash-15-sum(v['net'] for v in records))<1e-7
    wins=[v['net'] for v in records if v['net']>0];losses=[-v['net'] for v in records if v['net']<=0]
    return dict(capital=cash,return_pct=(cash/15-1)*100,max_capital=peak,max_capital_ms=peak_ms,
        max_drawdown_pct=dd,drawdown_event=drawdown_event,trades=len(records),wins=len(wins),losses=len(losses),
        fees=sum(v['fees'] for v in records),funding=sum(v['funding'] for v in records),
        liquidations=liquidations,ruined=cash<=1e-8,untradeable=cash<1,maximum_positions=max_open,
        milestones=high_water,rejected=rejected,curve=curve[::4]+curve[-1:],
        allocations=allocations[-240:],last_historical_allocation=terminal_positions,
        attribution={s:sum(v['net'] for v in records if v['symbol']==s) for s in symbols},records=records)
