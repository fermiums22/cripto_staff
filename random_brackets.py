"""Random long/short bracket grid; chronological selection, never real orders."""
import json
import math
import random
import statistics
import time
import agent
from window_experiment import collect


def hit(bar,side,entry,tp,sl):
    stop=entry*(1-side*sl);take=entry*(1+side*tp)
    if side*(bar[1]-stop)<=0:return bar[1],'stop'
    if side*(bar[1]-take)>=0:return bar[1],'take'
    if (bar[3]<=stop if side==1 else bar[2]>=stop):return stop,'stop'
    if (bar[2]>=take if side==1 else bar[3]<=take):return take,'take'
    return None


def simulate(data,a,b,tp,sl,seed,friction=.0006):
    rng=random.Random(seed);cash=10.;pos=None;fee=.001;fees=0.;fund=0.;trades=0;wins=0;win_sum=0.;loss_sum=0.;held=[];curve=[];peak=10.;dd=0.;halt=False
    lot=data['instrument']['lotSizeFilter'];step=float(lot['qtyStep']);mmr=float(data['risk']['maintenanceMargin'])
    rates={int(r['fundingRateTimestamp']):float(r['fundingRate']) for r in data['funding']}
    for i in range(a,b):
        bar=data['trade'][i];mark=data['mark'][i];ts=bar[0]
        if pos and ts in rates:
            cost=-pos['side']*pos['qty']*mark[1]*rates[ts];cash+=cost;fund+=cost;pos['fund']+=cost
        if not pos and not halt:
            side=rng.choice((-1,1));entry=bar[1]*(1+side*friction)
            qty=math.floor(cash*.25*10/entry/step)*step
            value=qty*entry
            if qty>=float(lot['minOrderQty']) and value>=float(lot['minNotionalValue']) and value/10+2*value*fee<=cash:
                commission=value*fee;cash-=commission;fees+=commission
                pos=dict(side=side,qty=qty,entry=entry,ts=ts,fee=commission,fund=0.)
        if pos:
            side=pos['side'];qty=pos['qty'];worst=mark[3] if side==1 else mark[2]
            liquidated=cash+side*qty*(worst-pos['entry'])<=qty*worst*(mmr+fee)
            exit_=(worst,'liquidation') if liquidated else hit(bar,side,pos['entry'],tp,sl)
            if exit_ is None and i==b-1:exit_=(bar[4],'end')
            if exit_:
                fill=exit_[0]*(1-side*friction);commission=qty*fill*fee
                gross=side*qty*(fill-pos['entry']);cash+=gross-commission;fees+=commission
                net=gross-commission-pos['fee']+pos['fund']
                wins+=net>0;win_sum+=max(0,net);loss_sum+=max(0,-net)
                trades+=1;held.append((ts+60000-pos['ts'])/60000)
                pos=None
                if liquidated:cash=max(0,cash);halt=True
        value=cash
        if pos:
            fill=bar[4]*(1-pos['side']*friction)
            value+=pos['side']*pos['qty']*(fill-pos['entry'])-pos['qty']*fill*fee
        peak=max(peak,value);dd=max(dd,100*(1-value/peak))
        if i%60==0 or i==b-1:curve.append([ts+60000,value])
    return dict(return_pct=(cash/10-1)*100,end_equity=cash,trades=trades,wins=wins,win_sum=win_sum,loss_sum=loss_sum,fees=fees,funding=fund,
        mean_hold_minutes=statistics.mean(held) if held else None,max_drawdown_pct=dd,curve=curve)


def summary(runs):
    total_trades=sum(r['trades'] for r in runs)
    wins=sum(r['wins'] for r in runs);losses=total_trades-wins
    avg_win=sum(r['win_sum'] for r in runs)/wins if wins else 0
    avg_loss=sum(r['loss_sum'] for r in runs)/losses if losses else 0
    return dict(mean_pct=statistics.mean(r['return_pct'] for r in runs),worst_pct=min(r['return_pct'] for r in runs),
        best_pct=max(r['return_pct'] for r in runs),mean_trades=statistics.mean(r['trades'] for r in runs),
        win_rate_pct=100*sum(r['wins'] for r in runs)/total_trades if total_trades else None,
        mean_win_usdt=avg_win,mean_loss_usdt=avg_loss,
        sample_break_even_pct=100*avg_loss/(avg_win+avg_loss) if avg_win+avg_loss else None,
        positive_seeds=sum(r['return_pct']>0 for r in runs),seeds=len(runs))


def run():
    data=collect();n=len(data['trade']);cut=n*5//7;rows=[]
    for tp in (.003,.006,.01):
        for sl in (.001,.003,.006):
            runs=[simulate(data,0,cut,tp,sl,s) for s in range(5)]
            rows.append(dict(tp=tp,sl=sl,validation=summary(runs)))
    selected=max(range(len(rows)),key=lambda i:rows[i]['validation']['mean_pct'])
    for r in rows:
        r['test']=summary([simulate(data,cut,n,r['tp'],r['sl'],s) for s in range(100,105)])
    chosen=rows[selected]
    detailed=[simulate(data,cut,n,chosen['tp'],chosen['sl'],s) for s in range(100,105)]
    stress=summary([simulate(data,cut,n,chosen['tp'],chosen['sl'],s,friction=.0013) for s in range(100,105)])
    report=dict(created_ms=int(time.time()*1000),start_ms=data['start_ms'],split_ms=data['trade'][cut][0],end_ms=data['end_ms']+60000,
        candidates=rows,selected_index=selected,selected_runs=detailed,stress=stress,
        notes='SOLUSDT futures, $10, leverage10, 25% wallet initial margin per position. One position, random side, immediate next-minute reentry. TP/SL price percentages. Select 9 combinations on first5days, evaluate last2days with new seeds. History previously inspected, not pristine holdout. Current taker .1% each side. Spread .02% plus slip .05% each side, stress .06% plus .1%. Funding and adverse mark extreme liquidation proxy. Stop-first OHLC, terminal liquidation of open positions. Current lot/MM rules; no execution queue, approximate cross margin. No live orders.')
    path=agent.ARTIFACTS/'random_brackets.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(report),encoding='utf-8');tmp.replace(path)
    print(json.dumps(dict(selected=chosen,stress=stress,all=rows)))


if __name__=='__main__':run()
