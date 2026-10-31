"""Independent research wallet with explicit mid-price cost attribution."""
from collections import defaultdict
from datetime import datetime,timezone
import numpy as np
from brain_evolution_env import ExplorationAccount
from brain_impulse_execution import consume


class Account(ExplorationAccount):
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw);self.halted=False;self.entry=None

    def book(self,q):
        before=self.position
        super().book(q)
        if before is None and self.position is not None:
            p=self.position;side=p['side'];levels=q['asks'] if side==1 else q['bids']
            self.entry=dict(mid=(q['asks'][0][0]+q['bids'][0][0])/2,top=levels[0][0],
                            value=consume(levels,p['qty']),mae=0.,mfe=0.)
        if self.position and self.position['symbol']==q['symbol']:
            p=self.position;mid=(q['bids'][0][0]+q['asks'][0][0])/2
            move=p['side']*(mid/self.entry['mid']-1)
            self.entry['mae']=min(self.entry['mae'],move);self.entry['mfe']=max(self.entry['mfe'],move)
        if self.drawdown>=.1:
            self.halted=True
            if self.pending and self.pending['kind']!='CLOSE':self.pending=None
            if self.position and not self.pending:self.act({'kind':'CLOSE'},q['ts'])

    def _close(self,q,reason,liquidation=False):
        p=dict(self.position);e=dict(self.entry);side=p['side'];qty=p['qty']
        levels=q['bids'] if side==1 else q['asks'];raw=consume(levels,qty)
        if raw is None:return super()._close(q,reason,liquidation)
        mid=(q['bids'][0][0]+q['asks'][0][0])/2
        midgross=side*qty*(mid-e['mid'])
        spread=side*qty*((e['top']-e['mid'])+(mid-levels[0][0]))
        impact=side*((e['value']-qty*e['top'])+(qty*levels[0][0]-raw))
        slippage=self.slip*(e['value']+raw)
        super()._close(q,reason,liquidation)
        t=self.trades[-1]
        t.update(mid_gross_pnl=midgross,spread=spread,depth_impact=impact,slippage=slippage,
                 funding=0. if q['ts']//3600000==p['opened_ms']//3600000 else None,
                 sampled_mae=min(e['mae'],side*(mid/e['mid']-1)),
                 sampled_mfe=max(e['mfe'],side*(mid/e['mid']-1)),holding_ms=q['ts']-p['opened_ms'])
        t['cost_residual']=midgross-spread-impact-slippage-t['fees']-t['net_pnl']
        if abs(t['cost_residual'])>1e-8:raise ValueError('Cost identity failed')
        self.entry=None

    def enter(self,symbol,side,now):
        if self.halted or self.position or self.pending:return
        self.act(dict(kind='BUY' if side==1 else 'SELL',symbol=symbol,fraction=min(.8,12/self.cash),
                      leverage=1.,stop=.01,hold_ms=120000),now)

    def result(self):
        r=self.report();r.pop('actions');tr=self.trades
        for k in ('mid_gross_pnl','spread','depth_impact','slippage'):
            r[k]=sum(t[k] for t in tr)
        r['funding']=None if any(t['funding'] is None for t in tr) else 0.
        r['average_net_pnl']=float(np.mean([t['net_pnl'] for t in tr])) if tr else None
        days=defaultdict(float)
        for t in tr:days[datetime.fromtimestamp(t['closed_ms']/1000,timezone.utc).strftime('%Y-%m-%d')]+=t['net_pnl']
        r['by_day']=dict(days);r['halted_at_10pct_drawdown']=self.halted
        r['uncertainty']='Only two historical development days; no defensible generalization confidence interval'
        r['independent_paper_evidence']=False
        return r
