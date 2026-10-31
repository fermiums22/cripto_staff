"""A: causal leader event delivery and lagging-alt selection; no outcome lookup."""
from collections import deque


class LeaderPolicy:
    def __init__(self,signals):
        self.signals=sorted((dict(s) for s in signals if s['leader']!='clock_control'),key=lambda s:s['signal_ms'])
        self.index=0;self.history={};self.curves=[];self.pending=[]

    def quote(self,q):
        symbol=q['symbol'];now=q['ts'];mid=(q['bids'][0][0]+q['asks'][0][0])/2
        h=self.history.setdefault(symbol,deque());h.append((now,mid))
        while h and h[0][0]<now-3000:h.popleft()
        keep=[]
        for p in self.pending:
            if p['symbol']==symbol:
                while p['next_second']<=120 and now>=p['signal_ms']+p['next_second']*1000:
                    second=p['next_second'];p['next_second']+=1
                    if now-p['signal_ms']-second*1000<=1500:
                        self.curves.append(dict(symbol=symbol,leader=p['leader'],signal_ms=p['signal_ms'],lag_seconds=second,
                            observed_ms=now,observation_delay_ms=now-p['signal_ms']-second*1000,
                            signed_mid_return=p['side']*(mid/p['mid']-1),lagging=p['lagging']))
            if p['next_second']<=120:keep.append(p)
        self.pending=keep

    def events(self,now,assets):
        choices=[]
        while self.index<len(self.signals) and self.signals[self.index]['signal_ms']<=now:
            s=self.signals[self.index];self.index+=1
            if now-s['signal_ms']>1500:continue
            for symbol in assets:
                h=self.history.get(symbol,());past=next((v for v in reversed(h) if v[0]<=s['signal_ms']-1000),None)
                current=next((v for v in reversed(h) if v[0]<=s['signal_ms']),None)
                if not past or not current or s['signal_ms']-current[0]>1500 or s['signal_ms']-1000-past[0]>1500:continue
                response=s['side']*(current[1]/past[1]-1);lagging=response<=abs(s['leader_return'])*.25
                self.pending.append(dict(symbol=symbol,mid=current[1],leader=s['leader'],side=s['side'],
                    signal_ms=s['signal_ms'],next_second=1,lagging=lagging))
                if lagging:choices.append((abs(s['leader_return'])-response,symbol,s['side']))
        return sorted(choices,key=lambda v:(-v[0],v[1]))


if __name__=='__main__':
    from research.compare import main
    main('A')
