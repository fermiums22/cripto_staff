"""Bounded historical experiment only: random hedged windows, no order API."""
import json
import math
import random
import statistics
import time

import agent


def collect(days=7):
    end=int(time.time()*1000)//60000*60000-60000;start=end-(days*1440-1)*60000
    path=agent.DATA/'window_history.json'
    if path.exists():
        cached=json.loads(path.read_text())
        if cached['end_ms']>=end-3600000:return cached
    result=dict(start_ms=start,end_ms=end,symbol='SOLUSDT')
    for name,endpoint in [('trade','kline'),('mark','mark-price-kline')]:
        rows={};cursor=end
        while cursor>=start:
            d=agent.api(endpoint,category='linear',symbol='SOLUSDT',interval='1',end=cursor,limit=1000)
            raw=d['result']['list']
            if not raw:raise ValueError('Missing futures history')
            for r in raw:
                ts=int(r[0])
                if start<=ts<=end:rows[ts]=[ts,*map(float,r[1:5])]
            oldest=min(int(r[0]) for r in raw)
            if oldest>cursor:raise ValueError('History cursor stalled')
            cursor=oldest-1
        if sorted(rows)!=list(range(start,end+1,60000)):raise ValueError('Minute gap')
        result[name]=[rows[t] for t in sorted(rows)]
    result['funding']=agent.api('funding/history',category='linear',symbol='SOLUSDT',startTime=start,endTime=end+59999,limit=200)['result']['list']
    if len(result['funding'])>=200:raise ValueError('Funding requires pagination')
    result['instrument']=agent.api('instruments-info',category='linear',symbol='SOLUSDT')['result']['list'][0]
    tiers=agent.api('risk-limit',category='linear',symbol='SOLUSDT')['result']['list']
    result['risk']=min(tiers,key=lambda r:float(r['riskLimitValue']))
    agent.DATA.mkdir(exist_ok=True);path.write_text(json.dumps(result),encoding='utf-8')
    return result


def equity(cash,positions,price,fee,friction):
    return cash+sum(p['qty']*p['side']*(price*(1-p['side']*friction)-p['entry'])
        -p['qty']*price*(1-p['side']*friction)*fee for p in positions)


def simulate(data,seed,fee=.001,spread=.0002,slip=.0005):
    rng=random.Random(seed);cash=10.;anchor=10.;positions=[];curve=[]
    leverage=10;sl=.10;target=.001;margin_per_window=2.;maximum=4
    friction=spread/2+slip;lot=data['instrument']['lotSizeFilter'];step=float(lot['qtyStep'])
    mmr=float(data['risk']['maintenanceMargin']);deduction=float(data['risk'].get('mmDeduction') or 0)
    funding={int(r['fundingRateTimestamp']):float(r['fundingRate']) for r in data['funding']}
    fees=0.;funding_cash=0.;opened=0;closed=0;stops=0;liquidations=0;wins=0;blocked=0;peak_open=0;peak=10.;dd=0.;last_entry=-10**15;last_side=None;insolvent=False
    def close_all(price):
        nonlocal cash,fees,closed,positions
        for p in positions:
            fill=price*(1-p['side']*friction);commission=p['qty']*fill*fee
            cash+=p['qty']*p['side']*(fill-p['entry'])-commission
            fees+=commission;closed+=1
        positions=[]
    for i,(bar,mark) in enumerate(zip(data['trade'],data['mark'])):
        ts=bar[0]
        # Funding at candle opening applies only to already open positions.
        if ts in funding:
            amount=-sum(p['side']*p['qty'] for p in positions)*mark[1]*funding[ts]
            cash+=amount;funding_cash+=amount
        # New windows use candle open; no future high/low/close informs entry.
        if not insolvent and (not positions or ts-last_entry>=1800000):
            side=rng.choice((-1,1)) if not positions else -last_side
            fill=bar[1]*(1+side*friction)
            qty=math.floor((margin_per_window*leverage/fill)/step)*step
            value=qty*fill;margin=value/leverage
            free=min(cash,equity(cash,positions,mark[1],fee,friction))-sum(p['margin'] for p in positions)
            if len(positions)<maximum and qty>=float(lot['minOrderQty']) and value>=float(lot['minNotionalValue']) and free>=margin+2*value*fee:
                cash-=value*fee;fees+=value*fee
                positions.append(dict(side=side,qty=qty,entry=fill,margin=margin))
                opened+=1;peak_open=max(peak_open,len(positions));last_entry=ts;last_side=side
            else:blocked+=1
        # Approximate cross-margin risk, no hedge margin credit. Liquidation before
        # beneficial exits in ambiguous minutes; not an exact Bybit risk engine.
        net=sum(p['side']*p['qty'] for p in positions)
        worst=mark[3] if net>=0 else mark[2]
        gross=sum(p['qty']*worst for p in positions)
        account=cash+sum(p['side']*p['qty']*(worst-p['entry']) for p in positions)
        maintenance=max(0,gross*mmr-deduction)+gross*fee
        if positions and account<=maintenance:
            close_all(worst);cash=max(0,cash);liquidations+=1;insolvent=True
        else:
            for p in positions[:]:
                level=p['entry']*(1-p['side']*sl)
                hit=bar[3]<=level if p['side']>0 else bar[2]>=level
                if hit:
                    raw=min(bar[1],level) if p['side']>0 else max(bar[1],level)
                    fill=raw*(1-p['side']*friction);commission=p['qty']*fill*fee
                    cash+=p['side']*p['qty']*(fill-p['entry'])-commission
                    fees+=commission;closed+=1;stops+=1;positions.remove(p)
            # Basket target on observable minute close only, includes prior stops,
            # entry fees and funding via cash, and estimated cost of every exit.
            if positions:
                target_cash=anchor+target*sum(p['qty']*p['entry'] for p in positions)
                if equity(cash,positions,bar[4],fee,friction)>=target_cash:
                    close_all(bar[4]);wins+=1;anchor=cash
        value=equity(cash,positions,bar[4],fee,friction)
        peak=max(peak,value);dd=max(dd,100*(1-value/peak))
        if i%30==0:curve.append([ts+60000,value])
    outstanding=len(positions);unrealized=equity(cash,positions,data['trade'][-1][4],fee,friction)-cash
    close_all(data['trade'][-1][4]);curve.append([data['end_ms']+60000,cash])
    return dict(seed=seed,end_equity=cash,return_pct=(cash/10-1)*100,entries=opened,exits=closed,
        basket_wins=wins,stop_exits=stops,liquidations=liquidations,fees=fees,funding=funding_cash,
        blocked_minutes=blocked,peak_windows=peak_open,terminal_positions=outstanding,
        terminal_unrealized_net=unrealized,max_drawdown_pct=dd,curve=curve)


def run():
    # These seeds produce opposite initial directions. More seeds merely repeat
    # these paths when no basket ever closes; do not imply independent evidence.
    data=collect();rows=[simulate(data,seed) for seed in (0,1)]
    stress=[simulate(data,seed,spread=.0006,slip=.001) for seed in (0,1)]
    report=dict(created_ms=int(time.time()*1000),start_ms=data['start_ms'],end_ms=data['end_ms']+60000,
        symbol='SOLUSDT',runs=rows,stress=stress,median_pct=statistics.median(r['return_pct'] for r in rows),
        settings=dict(capital=10,leverage=10,stop_price_pct=10,profit_nominal_pct=.1,add_after_minutes=30,
            window_margin=2,max_windows=4,fee_per_side=.001,spread=.0002,slippage_per_side=.0005),
        notes='Historical simulation only. Actual futures and mark candles, historical funding. Current lot/MM rules. Approximate cross margin, no hedge credits, stop/liquidation-first minute ordering. Independent virtual windows differ from exchange aggregated same-side positions. All terminal positions closed and costs included. No matching-engine guarantee, no live orders.')
    path=agent.ARTIFACTS/'window_experiment.json';path.parent.mkdir(exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(report),encoding='utf-8');tmp.replace(path)
    print(json.dumps({k:v for k,v in report.items() if k not in ('runs','stress')}))
    print(json.dumps([{k:v for k,v in r.items() if k!='curve'} for r in rows]))


if __name__=='__main__':run()
