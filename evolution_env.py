"""Minute-resolution research environment. No network or order interface."""
import math
import numpy as np
import gymnasium as gym
from execution_research import features


def market_features(data):
    bars=data['trade']
    if len(bars)!=len(data['mark']) or len(bars)<100:
        raise ValueError('Insufficient or misaligned history')
    for i,(bar,mark) in enumerate(zip(bars,data['mark'])):
        if bar[0]!=mark[0] or (i and bar[0]-bars[i-1][0]!=60000):
            raise ValueError('History gap')
    return np.asarray([[0.]*9 if i<30 else features(bars,i) for i in range(len(bars))],dtype=np.float32)


class TradingEnv(gym.Env):
    """0=wait/hold, 1=long, 2=short, 3=close; opposite entry closes first.

    Observation is at bar i close; action executes at i+1 open. Funding precedes
    orders at settlement. Single 1x position, conservative mark liquidation proxy.
    Episodes close all positions, including at training truncation. No top-ups.
    """
    metadata={}

    def __init__(self,data,x,mean,scale,start,end,fee=.001,friction=.0006,
                 allocation=.9,episode_bars=None,risk_penalty=0.):
        self.data=data;self.x=x;self.mean=mean;self.scale=scale
        self.start=start;self.end=end;self.fee=fee;self.friction=friction
        self.allocation=allocation;self.episode_bars=episode_bars;self.risk_penalty=risk_penalty
        self.rates={int(r['fundingRateTimestamp']):float(r['fundingRate']) for r in data['funding']}
        self.action_space=gym.spaces.Discrete(4)
        self.observation_space=gym.spaces.Box(-20,20,shape=(13,),dtype=np.float32)
        self.reset()

    def reset(self,seed=None,options=None):
        super().reset(seed=seed)
        self.i=self.start
        if self.episode_bars:
            self.i=int(self.np_random.integers(self.start,max(self.start+1,self.end-self.episode_bars)))
        self.stop=min(self.end,self.i+self.episode_bars) if self.episode_bars else self.end
        self.cash=15.;self.qty=0.;self.side=0;self.entry=0.;self.entry_index=0
        self.fees=0.;self.funding=0.;self.gross=0.;self.peak=15.;self.dd=0.
        self.last_equity=15.;self.trades=[];self.liquidations=0;self.halted=False
        self.curve=[[self.data['trade'][self.i][0]+60000,15.]]
        return self._obs(),{}

    def equity(self,price):
        if not self.side:return self.cash
        fill=price*(1-self.side*self.friction)
        return self.cash+self.qty*(self.side*(fill-self.entry)-fill*self.fee)

    def _obs(self):
        price=self.data['trade'][self.i][4]
        market=np.clip((self.x[self.i]-self.mean)/self.scale,-10,10)
        position=[self.side,self.qty*price/15,(self.equity(price)-15)/15,
                  (self.i-self.entry_index)/1440 if self.side else 0]
        return np.clip(np.r_[market,position],-20,20).astype(np.float32)

    def _close(self,price,reason,at_close=False):
        if not self.side:return
        fill=price*(1-self.side*self.friction);fee=self.qty*fill*self.fee
        gross=self.qty*self.side*(fill-self.entry)
        self.cash+=gross-fee;self.fees+=fee;self.gross+=gross
        self.trades.append(dict(entry_ms=self.entry_ms,exit_ms=self.data['trade'][self.i][0]+(60000 if at_close else 0),
            side=self.side,qty=self.qty,entry=self.entry,exit=fill,reason=reason,
            gross=gross,fees=self.entry_fee+fee,funding=self.position_funding,
            net=gross-self.entry_fee-fee+self.position_funding))
        self.qty=0.;self.side=0

    def step(self,action):
        if self.halted or self.i>=self.stop-1:raise RuntimeError('Reset completed episode')
        action=int(action);self.i+=1
        bar=self.data['trade'][self.i];mark=self.data['mark'][self.i]
        if self.side:
            amount=-self.side*self.qty*mark[1]*self.rates.get(bar[0],0.)
            self.cash+=amount;self.funding+=amount;self.position_funding+=amount
            maintenance=self.qty*mark[1]*float(self.data['risk']['maintenanceMargin'])
            if self.equity(mark[1])<=maintenance:
                self._close(mark[1],'gap_liquidation_proxy');self.liquidations+=1;self.halted=True
        target={1:1,2:-1}.get(action)
        if action==3 or (target and self.side and target!=self.side):self._close(bar[1],'decision')
        if target and not self.side and self.cash>12 and not self.halted:
            fill=bar[1]*(1+target*self.friction);lot=self.data['instrument']['lotSizeFilter']
            step=float(lot['qtyStep']);qty=math.floor(self.cash*self.allocation/(fill*(1+self.fee))/step)*step
            if qty>=float(lot['minOrderQty']) and qty*fill>=float(lot['minNotionalValue']):
                self.side=target;self.qty=qty;self.entry=fill;self.entry_index=self.i
                self.entry_ms=bar[0];self.entry_fee=qty*fill*self.fee;self.position_funding=0.
                self.cash-=self.entry_fee;self.fees+=self.entry_fee
        if self.side:
            adverse=mark[3] if self.side==1 else mark[2]
            value=self.equity(adverse)
            self.dd=max(self.dd,100*(1-value/self.peak))
            maintenance=self.qty*adverse*float(self.data['risk']['maintenanceMargin'])
            if value<=maintenance:
                self._close(adverse,'liquidation_proxy');self.liquidations+=1;self.halted=True
        value=self.equity(mark[4]);self.peak=max(self.peak,value)
        self.dd=max(self.dd,100*(1-value/self.peak))
        terminal=self.i>=self.stop-1 or value<=12 or self.halted
        if terminal:self._close(bar[4],'boundary' if self.i>=self.stop-1 else 'risk_halt',at_close=True)
        value=self.cash if terminal else value
        self.peak=max(self.peak,value);self.dd=max(self.dd,100*(1-value/self.peak))
        change=(value-self.last_equity)/15
        reward=100*(change-self.risk_penalty*max(0,-change))
        self.last_equity=value;self.curve.append([bar[0]+60000,value]);self.halted=terminal
        return self._obs(),reward,terminal,False,{}

    def report(self):
        wins=[t['net'] for t in self.trades if t['net']>0]
        losses=[-t['net'] for t in self.trades if t['net']<=0]
        return dict(capital=self.cash,return_pct=(self.cash/15-1)*100,trades=len(self.trades),
            wins=len(wins),fees=self.fees,funding=self.funding,gross=self.gross,
            max_drawdown_pct=self.dd,liquidations=self.liquidations,
            mean_win=float(np.mean(wins)) if wins else 0.,mean_loss=float(np.mean(losses)) if losses else 0.,
            curve=self.curve[::10]+self.curve[-1:])
