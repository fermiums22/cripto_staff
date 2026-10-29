"""Cross-asset gated sequence experts and shared-capital historical challenge."""
import csv
import gzip
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import torch
from torch import nn
from xgboost import XGBRegressor
import agent
from portfolio_market import write
from portfolio_sim import simulate

FEATURES=['return_15m','return_1h','return_4h','volatility_6h','volume_ratio','range',
          'btc_return_1h','eth_return_1h','btc_correlation','correlation_change','relative_strength',
          'btc_lag_return','funding_last_known','mark_trade_basis']


def build_features(market):
    n=len(next(iter(market.values()))['trade']);out={}
    closes={s:np.asarray([b[4] for b in d['trade']]) for s,d in market.items()}
    returns={s:np.r_[0,np.diff(np.log(c))] for s,c in closes.items()}
    for s,d in market.items():
        x=np.zeros((n,len(FEATURES)),dtype=np.float32);volume=np.asarray([b[5] for b in d['trade']])
        rates=sorted((int(v['fundingRateTimestamp']),float(v['fundingRate'])) for v in d['funding']);cursor=0;last=0.
        for i in range(96,n):
            # A settlement rate is used only after its timestamp, never its future value.
            while cursor<len(rates) and rates[cursor][0]<=d['trade'][i][0]:last=rates[cursor][1];cursor+=1
            def corr(a,b):
                return float(np.corrcoef(a,b)[0,1]) if np.std(a)>1e-10 and np.std(b)>1e-10 else 0.
            current=corr(returns[s][i-23:i+1],returns['BTCUSDT'][i-23:i+1])
            old=corr(returns[s][i-47:i-23],returns['BTCUSDT'][i-47:i-23])
            c=closes[s];bar=d['trade'][i]
            x[i]=[c[i]/c[i-1]-1,c[i]/c[i-4]-1,c[i]/c[i-16]-1,np.std(returns[s][i-23:i+1]),
                volume[i]/max(volume[i-24:i].mean(),1e-9),(bar[2]-bar[3])/c[i],
                closes['BTCUSDT'][i]/closes['BTCUSDT'][i-4]-1,
                closes['ETHUSDT'][i]/closes['ETHUSDT'][i-4]-1,current,current-old,
                c[i]/c[i-4]-closes['BTCUSDT'][i]/closes['BTCUSDT'][i-4],
                closes['BTCUSDT'][i-1]/closes['BTCUSDT'][i-5]-1,last,d['mark'][i][4]/c[i]-1]
        out[s]=x
    return out


class Experts(nn.Module):
    def __init__(self):
        super().__init__();self.groups=[list(range(6)),list(range(6,12)),[0,3,4,12,13]]
        self.encoders=nn.ModuleList([nn.GRU(len(g),16,batch_first=True) for g in self.groups])
        self.heads=nn.ModuleList([nn.Linear(16,1) for _ in self.groups])
        self.gate=nn.Sequential(nn.Linear(len(FEATURES),24),nn.Tanh(),nn.Linear(24,3))
    def forward(self,x):
        predictions=torch.cat([head(encoder(x[:,:,group])[1][-1]) for group,encoder,head in zip(self.groups,self.encoders,self.heads)],dim=1)
        weights=torch.softmax(self.gate(x[:,-1]),dim=1)
        return (predictions*weights).sum(dim=1),weights


def run():
    torch.set_num_threads(2);torch.manual_seed(42);rng=np.random.default_rng(42)
    root=agent.ARTIFACTS/'portfolio'/time.strftime('%Y%m%dT%H%M%SZ',time.gmtime());root.mkdir(parents=True)
    def status(stage,**kw):write(agent.ARTIFACTS/'portfolio_status.json',dict(stage=stage,run=root.name,updated_ms=int(time.time()*1000),**kw));print(stage,kw,flush=True)
    status('loading')
    directory=agent.DATA/'portfolio';manifest=json.loads((directory/'manifest.json').read_text())
    market={s:json.loads(gzip.decompress((directory/(s+'.json.gz')).read_bytes())) for s in manifest['symbols']}
    if not {'BTCUSDT','ETHUSDT','SOLUSDT'}.issubset(market):raise ValueError('Reference markets missing')
    n=len(market['BTCUSDT']['trade']);train=n//2;cut=n*2//3
    reference=[b[0] for b in market['BTCUSDT']['trade']]
    for s,d in market.items():
        if [b[0] for b in d['trade']]!=reference or [b[0] for b in d['mark']]!=reference:raise ValueError('Misaligned markets')
        if any(int(v['fundingRateTimestamp'])%900000 for v in d['funding']):raise ValueError('Funding not on candle boundary')
        raw=(directory/(s+'.json.gz')).read_bytes();(root/(s+'.json.gz')).write_bytes(raw)
    status('features',symbols=len(market),bars=n)
    raw_x=build_features(market);symbols=sorted(market)
    fit=np.concatenate([raw_x[s][96:train] for s in symbols]);mean=fit.mean(axis=0);scale=fit.std(axis=0);scale[scale<1e-7]=1
    x={s:np.clip((v-mean)/scale,-10,10).astype(np.float32) for s,v in raw_x.items()}
    target={s:np.asarray([d['trade'][min(i+4,n-1)][4]/d['trade'][min(i+1,n-1)][1]-1 for i in range(n)],dtype=np.float32) for s,d in market.items()}
    pairs=np.array([(j,i) for j in range(len(symbols)) for i in range(112,train-5,2)])
    if len(pairs)>60000:pairs=pairs[rng.choice(len(pairs),60000,replace=False)]
    device='cuda' if torch.cuda.is_available() else 'cpu'
    model=Experts().to(device);optimizer=torch.optim.Adam(model.parameters(),lr=.001)
    initial=torch.cat([v.detach().flatten() for v in model.parameters()]).clone();losses=[]
    for epoch in range(8):
        status('training_moe',epoch=epoch+1,epochs=8,device=device)
        rng.shuffle(pairs);total=[];model.train()
        for k in range(0,len(pairs),512):
            batch=pairs[k:k+512];xb=np.stack([x[symbols[j]][i-15:i+1] for j,i in batch]);yb=np.array([target[symbols[j]][i]*100 for j,i in batch])
            prediction,_=model(torch.from_numpy(xb).to(device));loss=nn.functional.smooth_l1_loss(prediction,torch.from_numpy(yb).to(device))
            optimizer.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1);optimizer.step();total.append(float(loss.detach().cpu()))
        losses.append(float(np.mean(total)))
    delta=float(torch.linalg.vector_norm(torch.cat([v.detach().flatten() for v in model.parameters()])-initial).cpu())
    if delta<=0:raise ValueError('Weights unchanged')
    torch.save(model.cpu().state_dict(),root/'experts.pt');model.eval();prediction={};gates={}
    for s in symbols:
        values=np.zeros(n);weights=np.zeros((n,3))
        with torch.no_grad():
            for a in range(112,n,512):
                indices=range(a,min(a+512,n));batch=torch.from_numpy(np.stack([x[s][i-15:i+1] for i in indices]))
                p,w=model(batch);values[a:a+len(p)]=p.numpy()/100;weights[a:a+len(p)]=w.numpy()
        prediction[s]=values;gates[s]=weights
    status('training_xgboost',device='cuda')
    tx=np.array([raw_x[symbols[j]][i] for j,i in pairs]);ty=np.array([target[symbols[j]][i] for j,i in pairs])
    tree=XGBRegressor(n_estimators=200,max_depth=4,learning_rate=.03,device='cuda',tree_method='hist',random_state=42,n_jobs=2)
    tree.fit(tx,ty)
    if 'cuda' not in json.loads(tree.get_booster().save_config())['learner']['generic_param']['device']:raise ValueError('GPU unavailable')
    tree.save_model(root/'xgboost.json');tree.set_params(device='cpu');tree_prediction={s:tree.predict(raw_x[s]) for s in symbols}
    forecasts={'moe':prediction,'xgb':tree_prediction,
        'momentum':{s:raw_x[s][:,1] for s in symbols},
        'cross_asset':{s:.5*(raw_x[s][:,6]+raw_x[s][:,7])-raw_x[s][:,1] for s in symbols},
        'cash':{s:np.zeros(n) for s in symbols}}
    # Costs are a conservative scenario based on observed SOL fee, not verified for every symbol.
    fee=float(json.loads((agent.ARTIFACTS/'execution_fees.json').read_text())['taker'])
    candidates=[]
    status('validation',symbols=len(symbols))
    for family,pred in forecasts.items():
        for mode in (('single','best','multi') if family in ('moe','xgb') else ('multi',)):
            for leverage in ((1,3,10) if family!='cash' else (1,)):
                r=simulate(market,pred,train,cut,mode=mode,leverage=leverage,fee=fee)
                candidates.append(dict(name=f'{family}_{mode}_{leverage}x',family=family,mode=mode,leverage=leverage,
                    validation=compact(r),score=r['return_pct']-.5*r['max_drawdown_pct']))
    selected=max(candidates,key=lambda v:(v['score'],v['family']=='cash'))['name']
    write(root/'selection.json',dict(selected=selected,candidates=candidates))
    status('final_test',selected=selected)
    for c in candidates:
        pred=forecasts[c['family']];kwargs=dict(mode=c['mode'],leverage=c['leverage'],fee=fee)
        result=simulate(market,pred,cut,n,**kwargs)
        with (root/(c['name']+'.csv')).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(result['records'][0]) if result['records'] else ['net']);w.writeheader();w.writerows(result['records'])
        c['test']=compact(result);c['test']['allocations']=result['allocations'];c['test']['attribution']=result['attribution']
        c['stress']=compact(simulate(market,pred,cut,n,friction=.0016,**kwargs))
        c['subperiods']=[compact(simulate(market,pred,a,b,**kwargs)) for a,b in
            zip([cut,cut+(n-cut)//3,cut+2*(n-cut)//3],[cut+(n-cut)//3,cut+2*(n-cut)//3,n])]
    # Gate statistics describe routing, not causal feature importance.
    routing={s:dict(zip(['own_sequence','cross_asset','funding_basis'],gates[s][cut:].mean(axis=0).tolist())) for s in symbols}
    importance=dict(zip(FEATURES,tree.feature_importances_.tolist()))
    report=dict(run=root.name,created_ms=int(time.time()*1000),manifest=manifest,
        train_end_ms=reference[train],test_start_ms=reference[cut],end_ms=reference[-1]+900000,
        selected=selected,candidates=candidates,neural_device=device,weight_delta_l2=delta,training_losses=losses,
        routing=routing,xgb_importance=importance,fee_assumption=fee,auto_promoted=False,
        limitations=['Current surviving/liquid universe; historical delistings and historical spread unknown.',
            '15-minute isolated-margin liquidation approximation, not exchange liquidation engine.',
            'Same fee scenario for all symbols; historical rules and personal symbol-specific fees not reconstructed.',
            'No OI/book/news features in historical model until timestamped coverage exists.',
            'Prior PPO experiment uses different data/execution and is not ranked as a comparable challenger.'])
    write(root/'config.json',dict(seed=42,features=FEATURES,mean=mean.tolist(),scale=scale.tolist(),epochs=8,
        history_hashes={s:hashlib.sha256((root/(s+'.json.gz')).read_bytes()).hexdigest() for s in symbols}))
    for name in ('portfolio_market.py','portfolio_research.py','portfolio_sim.py'):(root/name).write_bytes(Path(name).read_bytes())
    write(root/'report.json',report);write(agent.ARTIFACTS/'portfolio_research.json',report)
    status('complete',selected=selected)
    print(json.dumps({c['name']:round(c['test']['return_pct'],3) for c in candidates}),flush=True)


def compact(r):return {k:v for k,v in r.items() if k not in ('records','allocations','last_historical_allocation','attribution')}


if __name__=='__main__':
    try:run()
    except Exception as exc:
        write(agent.ARTIFACTS/'portfolio_status.json',dict(stage='failed',error=type(exc).__name__,updated_ms=int(time.time()*1000)));raise
