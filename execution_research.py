"""GPU barrier-label research and auditable maker-first execution approximation."""
import csv
import json
import math
import time
import agent
from random_brackets import hit

HORIZON=60


def features(bars,i):
    close=bars[i][4];past=bars[i-30:i];volume=sum(b[5] for b in past)/30
    return [close/bars[i-k][4]-1 for k in (1,3,5,15,30)]+[
        (max(b[2] for b in past)-min(b[3] for b in past))/close,
        bars[i][5]/volume if volume else 0,(bars[i][2]-bars[i][3])/close,
        (bars[i][0]//3600000%24)/24]


def outcome(data,i,tp,sl,mode,maker,taker,end=None,slip=.0005):
    bars=data['trade'];end=len(bars) if end is None else end
    side=1 if bars[i][4]>=bars[i-5][4] else -1
    opened=i+1
    if opened>=end:return None
    limit=bars[i][4]*(1-side*.0001)
    if mode=='maker':
        # Reject a post-only order that would cross the modeled opposite quote.
        opposite=bars[opened][1]*(1+side*.0001)
        if side*(limit-opposite)>=0:return None
        fill=None
        for j in range(opened,min(opened+3,end)):
            through=bars[j][3]<=limit*(1-.0002) if side==1 else bars[j][2]>=limit*(1+.0002)
            if through:fill=j;break
        if fill is None:return None
        opened=fill;entry=limit;reference_entry=limit;entry_fee=maker
    else:
        reference_entry=bars[opened][1];entry=reference_entry*(1+side*(.0001+slip));entry_fee=taker
    funding=0.;mfe=0.;mae=0.;reason=None
    rates=data.get('_rates',{})
    for j in range(opened,min(opened+HORIZON,end)):
        b=bars[j];mark=data['mark'][j]
        if j>opened and b[0] in rates:funding-=side*mark[1]*rates[b[0]]
        h=hit(b,side,entry,tp,sl)
        if mode=='maker' and j==opened and h and h[1]=='take':h=None
        if not h and (j==opened+HORIZON-1 or j==end-1):h=(b[4],'end' if j==end-1 else 'timeout')
        if h:
            reference_exit,reason=h;exit_price=reference_exit*(1-side*(.0001+slip));break
        if j>opened:
            favorable=b[2] if side==1 else b[3];adverse=b[3] if side==1 else b[2]
            mfe=max(mfe,side*(favorable/entry-1));mae=max(mae,-side*(adverse/entry-1))
    gross=side*(exit_price-entry);fees=entry*entry_fee+exit_price*taker
    return dict(signal_ms=bars[i][0]+60000,entry_ms=bars[opened][0],exit_ms=bars[j][0]+60000,
        exit_index=j,entry=entry,exit=exit_price,side='Buy' if side==1 else 'Sell',
        entry_type=mode,exit_type='taker',tp=tp,sl=sl,reason=reason,
        quote_pnl_per_unit=side*(reference_exit-reference_entry),gross_per_unit=gross,
        fees_per_unit=fees,funding_per_unit=funding,net_per_unit=gross-fees+funding,
        mfe_observed_pct=mfe*100,mae_observed_pct=mae*100)


def backtest(data,probs,a,b,tp,sl,mode,threshold,amplitude,maker,taker,slip=.0005):
    bars=data['trade'];cash=15.;records=[];curve=[[bars[a][0],cash]];attempts=0;unfilled=0;i=a
    lot=data['instrument']['lotSizeFilter'];step=float(lot['qtyStep']);peak=15.;dd=0.
    while i<b-1:
        entry_fee=maker if mode=='maker' else taker
        if probs.get(i,0)<threshold or (amplitude and features(bars,i)[5]<2*(entry_fee+taker+2*(.0001+slip))):i+=1;continue
        attempts+=1;r=outcome(data,i,tp,sl,mode,maker,taker,b,slip)
        if r is None:unfilled+=1;i+=4;continue
        # 1x, 90% cash, one position: no leveraged amplification in this experiment.
        qty=math.floor(cash*.9/(r['entry']*(1+taker))/step)*step
        if qty<float(lot['minOrderQty']) or qty*r['entry']<float(lot['minNotionalValue']):break
        before=cash
        accrued=0.
        for j in range(i+1,r['exit_index']+1):
            if bars[j][0]<r['entry_ms']:continue
            side=1 if r['side']=='Buy' else -1
            if bars[j][0]>r['entry_ms']:accrued-=side*data['mark'][j][1]*data.get('_rates',{}).get(bars[j][0],0)
            mark=bars[j][4]*(1-side*(.0001+slip));value=before+qty*(side*(mark-r['entry'])-r['entry']*entry_fee-mark*taker+accrued)
            peak=max(peak,value);dd=max(dd,100*(1-value/peak))
        r=dict(r,qty=qty,probability=probs[i],gross_pnl=r['gross_per_unit']*qty,
               fees=r['fees_per_unit']*qty,funding=r['funding_per_unit']*qty,net_pnl=r['net_per_unit']*qty)
        cash+=r['net_pnl'];r['balance']=cash;records.append(r)
        peak=max(peak,cash);dd=max(dd,100*(1-cash/peak));curve.append([r['exit_ms'],cash])
        i=r['exit_index']+1
        if cash<=12:break
    curve.append([bars[b-1][0]+60000,cash])
    wins=[r['net_pnl'] for r in records if r['net_pnl']>0];losses=[-r['net_pnl'] for r in records if r['net_pnl']<=0]
    return dict(return_pct=(cash/15-1)*100,trades=len(records),wins=len(wins),
        mean_win=sum(wins)/len(wins) if wins else 0,mean_loss=sum(losses)/len(losses) if losses else 0,
        gross_pnl=sum(r['gross_pnl'] for r in records),fees=sum(r['fees'] for r in records),
        funding=sum(r['funding'] for r in records),net_pnl=cash-15,attempts=attempts,unfilled=unfilled,
        max_drawdown_pct=dd,curve=curve),records


def run():
    data=json.loads((agent.DATA/'execution_history.json').read_text());bars=data['trade'];n=len(bars)
    data['_rates']={int(r['fundingRateTimestamp']):float(r['fundingRate']) for r in data['funding']}
    fees=json.loads((agent.ARTIFACTS/'execution_fees.json').read_text());maker=float(fees['maker']);taker=float(fees['taker'])
    train=n*4//7;cut=n*5//7;xs={i:features(bars,i) for i in range(30,n)}
    candidates={};predictions={};models={}
    for tp,sl in ((.006,.004),(.01,.006)):
        for mode in ('taker','maker'):
            indices=list(range(30,train-HORIZON-4,3))
            labels=[]
            for i in indices:
                r=outcome(data,i,tp,sl,mode,maker,taker,train)
                labels.append(int(r is not None and r['reason']=='take' and r['net_per_unit']>0))
            model=agent.fit_model([xs[i] for i in indices],labels)
            base=f'{mode}_{tp}_{sl}';models[base]=model
            indices=list(range(train,n));p=dict(zip(indices,agent.probabilities(model,[xs[i] for i in indices])))
            predictions[base]=p
            for threshold in (.5,.65,.8):
                for amplitude in (False,True):
                    key=f'{base}_{threshold}_{int(amplitude)}'
                    validation,_=backtest(data,p,train,cut,tp,sl,mode,threshold,amplitude,maker,taker)
                    candidates[key]=dict(tp=tp,sl=sl,mode=mode,threshold=threshold,amplitude=amplitude,validation=validation,base=base)
    eligible=[k for k,r in candidates.items() if r['validation']['trades']>=5]
    selected=max(eligible,key=lambda k:candidates[k]['validation']['return_pct']) if eligible else None
    # Evaluate the frozen selection only. No selecting by final-period results.
    report=dict(created_ms=int(time.time()*1000),train_end_ms=bars[train][0],test_start_ms=bars[cut][0],end_ms=bars[-1][0]+60000,
        candidates=candidates,selected=selected,fees=fees,training_device='cuda',test=None,stress=None,auto_promoted=False)
    if selected:
        r=candidates[selected];args=(data,predictions[r['base']],cut,n,r['tp'],r['sl'],r['mode'],r['threshold'],r['amplitude'],maker,taker)
        report['test'],records=backtest(*args);report['stress'],_=backtest(*args,slip=.001)
        report['unfiltered_test'],_=backtest(data,{i:1 for i in range(cut,n)},cut,n,r['tp'],r['sl'],r['mode'],0,False,maker,taker)
        with (agent.ARTIFACTS/'execution_trades.csv').open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(records[0]) if records else ['entry_ms','exit_ms','net_pnl']);writer.writeheader();writer.writerows(records)
    report['notes']='SOLUSDT futures 1x; train4days, validation1day, test2days, purged60+4min labels. Existing history previously studied. Maker fill proxy: post-only crossing rejection, 3min TTL, trade-through .02%, no favorable exit on fill bar. No queue/latency ground truth. MFE/MAE observed on fully held interior bars only. Fee rates account-verified. Cash $15, 90% notional, 20% halt, forced terminal exit. No real orders.'
    (agent.ARTIFACTS/'execution_models.json').write_text(json.dumps(models))
    path=agent.ARTIFACTS/'execution_research.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(report));tmp.replace(path)
    print(json.dumps({k:v for k,v in report.items() if k not in ('candidates','notes')}))


if __name__=='__main__':run()
