"""Action policies and financial-fitness evolutionary mutations, EXPLORATION only."""
import copy
import numpy as np
import torch
from torch import nn
from brain_impulse_data import FEATURES


class PolicyNet(nn.Module):
    def __init__(self,kind):
        super().__init__();self.kind=kind
        self.embed=nn.Sequential(nn.Linear(30,32),nn.Tanh())
        if kind=='moe':
            self.gate=nn.Linear(32,3);self.experts=nn.ModuleList([nn.Linear(32,7) for _ in range(3)])
        else:self.head=nn.Linear(32,7)

    def forward(self,x):
        h=self.embed(x)
        if self.kind=='moe':return (torch.stack([e(h) for e in self.experts],-1)*self.gate(h).softmax(-1)[:,None,:]).sum(-1)
        return self.head(h)


def population(seed=7301):
    torch.manual_seed(seed);result=[]
    for kind in ('cash','momentum','breakout','leadlag','orderflow','impulse','specialist'):
        result.append(dict(id=kind+'-g0',family=kind,architecture='rule',generation=0,parent=None,
            gain=1.,fraction=.7,leverage=1.,hold_ms=60000,stop=.01,symbol=0 if kind=='specialist' else None,
            reward_risk=.25))
    for parent in list(result):
        if parent['family']=='cash':continue
        child=copy.deepcopy(parent);child.update(id=parent['family']+'-aggressive-g0',gain=2.,fraction=1.,leverage=5.,hold_ms=30000,stop=.03)
        result.append(child)
    baseline=copy.deepcopy(next(c for c in result if c['id']=='momentum-g0'))
    baseline.update(id='momentum-baseline',family='baseline');result.append(baseline)
    for i,kind in enumerate(('mlp','moe','mlp','moe')):
        net=PolicyNet(kind)
        result.append(dict(id=kind+str(i)+'-g0',family='neural',architecture=kind,generation=0,parent=None,
            weights={k:v.detach().cpu().clone() for k,v in net.state_dict().items()},
            symbol=i if i==2 else None,reward_risk=(0.,.25,.5,1.)[i]))
    return result


def outputs(candidate,x,mean,std,device='cuda'):
    if candidate['architecture']!='rule':
        net=PolicyNet(candidate['architecture']).to(device);net.load_state_dict(candidate['weights']);net.eval()
        parts=[]
        with torch.no_grad():
            for start in range(0,len(x),4096):
                z=np.clip((x[start:start+4096]-mean)/std,-8,8).astype('float32')
                parts.append(net(torch.from_numpy(z).to(device)).cpu().numpy())
        return np.concatenate(parts)
    y=np.zeros((len(x),7),dtype='float32');kind=candidate['family'];g=candidate['gain']
    if kind=='cash':y[:,1]=-100;return y
    if kind in ('momentum','baseline'):score=x[:,1]*500
    elif kind=='breakout':score=x[:,0]*700+x[:,4]*500
    elif kind=='leadlag':score=(x[:,21]+x[:,22])*400
    elif kind=='orderflow':score=x[:,7]+x[:,13]*.7+x[:,8]*.5
    elif kind=='impulse':score=x[:,4]*700+x[:,0]*300+np.tanh(x[:,15])*np.sign(x[:,0])*.2
    else:score=x[:,0]*500+x[:,7]*.4
    y[:,0]=score*g;y[:,1]=np.abs(score)*g-.1
    # Remaining rule decisions use explicit mutable genome values.
    return y


def action(candidate,values,symbol,position,now):
    v=np.asarray(values,dtype='float64')
    if not np.isfinite(v).all():raise ValueError('Nonfinite policy output')
    if candidate['family']=='cash':return dict(kind='NO TRADE')
    if candidate.get('symbol') is not None and candidate['symbol']!=symbol:return dict(kind='HOLD' if position else 'NO TRADE')
    if position:
        close=(v[0]*position['side']<-.15 or (candidate['architecture']!='rule' and v[6]>.5))
        return dict(kind='CLOSE' if close and now-position['opened_ms']>=5000 else 'HOLD')
    if v[1]<=0:return dict(kind='NO TRADE')
    if candidate['architecture']=='rule':
        fraction=candidate['fraction'];leverage=candidate['leverage'];hold=candidate['hold_ms'];stop=candidate['stop']
    else:
        sig=1/(1+np.exp(-np.clip(v,-30,30)))
        fraction=.2+.8*sig[2];leverage=1+9*sig[3]
        hold=int(10000+170000*sig[4]);stop=.003+.077*sig[5]
    return dict(kind='BUY' if v[0]>=0 else 'SELL',fraction=float(fraction),leverage=float(leverage),
        hold_ms=int(hold),stop=float(stop))


def fitness(report,risk):
    if report['evidence_issues']:return -1e6
    # No activity/inaction bonus. Cash is zero, losses remain losses.
    return float(report['net_return']-risk*report['max_drawdown'])


def evolve(pop,reports,generation,seed):
    rng=np.random.default_rng(seed+generation);next_pop=[]
    # Preserve distinct hypotheses; never collapse the whole population into CASH.
    groups=('momentum','breakout','leadlag','orderflow','impulse','specialist','neural')
    next_pop.append(copy.deepcopy(next(c for c in pop if c['family']=='cash')))
    next_pop.append(copy.deepcopy(next(c for c in pop if c['family']=='baseline')))
    for family in groups:
        members=[c for c in pop if c['family']==family]
        members.sort(key=lambda c:fitness(reports[c['id']],c['reward_risk']),reverse=True)
        count=4 if family=='neural' else 2
        for index in range(count):
            parent=members[0 if family!='neural' else index%min(2,len(members))];child=copy.deepcopy(parent)
            child.update(id=f'{family}-g{generation}-{index}',parent=parent['id'],generation=generation)
            if child['architecture']=='rule' and index!=0:
                child['gain']=float(np.clip(child['gain']*np.exp(rng.normal(0,.25)),.2,4))
                child['fraction']=float(rng.choice([.3,.6,1.]))
                child['leverage']=float(rng.choice([1,2,5,10]))
                child['hold_ms']=int(rng.choice([10000,30000,60000,120000,180000]))
                child['stop']=float(rng.choice([.003,.01,.03,.08]))
                if family=='specialist':child['symbol']=int(rng.integers(4))
            elif index!=0:
                child['weights']={k:v+torch.from_numpy(rng.normal(0,.035,size=tuple(v.shape)).astype('float32')) for k,v in child['weights'].items()}
            next_pop.append(child)
    return next_pop
