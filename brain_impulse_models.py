"""Bounded GPU regression of eight after-cost outcomes; no promotion or orders.

Separate from immutable live controls. Caller must freeze the data and select
chronological folds; this module rejects overlap including feature lookback.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
import torch
from torch import nn
from brain_factory import thermal,save_checkpoint
from brain_impulse_dataset import load,LENGTH
from brain_impulse_data import FEATURES,atomic_json
from brain_archive_stream import sha

SEED=7301


class Frames:
    def __init__(self,directories):
        self.shards=[];self.offsets=[0];times=[];ends=[];starts=[];self.identities=[]
        for directory in map(Path,directories):
            meta,arrays=load(directory)
            for name,expected in meta['artifact_hashes'].items():
                if sha(directory/name)!=expected:raise ValueError('Dataset artifact changed')
            arrays={k:np.array(v) for k,v in arrays.items()}
            self.shards.append(arrays);self.offsets.append(self.offsets[-1]+len(arrays['targets']))
            times.append(arrays['signal_ms']);ends.append(arrays['exit_ms'])
            starts.append(arrays['feature_ms'][arrays['windows'][:,0]]-60000)
            self.identities.append(sha(directory/'dataset.json'))
        self.offsets=np.asarray(self.offsets,dtype='int64')
        self.times=np.concatenate(times);self.ends=np.concatenate(ends);self.input_start_ms=np.concatenate(starts)

    def batch(self,ids):
        ids=np.asarray(ids,dtype='int64')
        if np.any(ids<0) or np.any(ids>=self.offsets[-1]):raise ValueError('Dataset index outside bounds')
        x=np.empty((len(ids),LENGTH,len(FEATURES)),dtype='float32');y=np.empty((len(ids),8),dtype='float32')
        shards=np.searchsorted(self.offsets[1:],ids,side='right')
        for number in np.unique(shards):
            positions=np.where(shards==number)[0];local=ids[positions]-self.offsets[number]
            d=self.shards[number];x[positions]=d['features'][d['windows'][local]];y[positions]=d['targets'][local]
        return x,y


class ImpulseNet(nn.Module):
    def __init__(self,kind,width=32):
        super().__init__();self.kind=kind
        self.embed=nn.Linear(len(FEATURES),width)
        if kind=='mlp':self.encoder=nn.Sequential(nn.Flatten(1),nn.Linear(LENGTH*width,width),nn.SiLU())
        elif kind=='tcn':self.encoder=nn.Sequential(nn.Conv1d(width,width,3),nn.SiLU(),nn.Conv1d(width,width,3,dilation=2),nn.SiLU())
        elif kind=='gru':self.encoder=nn.GRU(width,width,batch_first=True)
        elif kind=='moe':
            self.gate=nn.Linear(width,3)
            self.experts=nn.ModuleList([nn.Sequential(nn.Linear(width,width),nn.SiLU(),nn.Linear(width,8)) for _ in range(3)])
        else:raise ValueError('Unknown impulse architecture')
        if kind!='moe':self.head=nn.Linear(width,8)

    def forward(self,x):
        h=self.embed(x)
        if self.kind=='moe':
            h=h.mean(1);weights=self.gate(h).softmax(-1)
            return (torch.stack([expert(h) for expert in self.experts],-1)*weights[:,None,:]).sum(-1)
        if self.kind=='tcn':h=self.encoder(h.transpose(1,2))[:,:,-1]
        elif self.kind=='gru':
            with torch.autocast(device_type=h.device.type,enabled=False):h=self.encoder(h.float())[0][:,-1]
        else:h=self.encoder(h)
        return self.head(h)


def validate_split(data,train,validation):
    if not len(train) or not len(validation):raise ValueError('Empty split')
    if np.max(data.ends[train])>=np.min(data.input_start_ms[validation]):
        raise ValueError('Train targets overlap validation feature lookback')


def scale_train(data,ids):
    total=np.zeros(len(FEATURES));squares=np.zeros(len(FEATURES));count=0
    for start in range(0,len(ids),2048):
        x,_=data.batch(ids[start:start+2048]);x=x.astype('float64')
        if not np.isfinite(x).all():raise ValueError('Invalid training features')
        total+=x.sum((0,1));squares+=(x*x).sum((0,1));count+=x.shape[0]*x.shape[1]
    mean=total/count;std=np.sqrt(np.maximum(squares/count-mean*mean,1e-12))
    return mean.astype('float32'),std.astype('float32')


def predict(net,data,ids,mean,std):
    net.eval();parts=[]
    with torch.no_grad():
        for start in range(0,len(ids),1024):
            x,_=data.batch(ids[start:start+1024]);z=np.clip((x-mean)/std,-10,10)
            parts.append(net(torch.from_numpy(z).cuda()).float().cpu().numpy()/100)
    return np.concatenate(parts) if parts else np.empty((0,8),dtype='float32')


def optimizer_step(net,opt,amp,tx,ty):
    """Retry finite-loss FP16 overflow at lower scale, without updating weights.

    Nonfinite loss or FP32 norm remains a hard failure. Retries are bounded and
    never skip a training example or silently accept invalid optimizer state.
    """
    for retry in range(8):
        opt.zero_grad(set_to_none=True)
        with torch.autocast('cuda',dtype=torch.float16):
            loss=nn.functional.smooth_l1_loss(net(tx),ty,beta=.2)
        if not torch.isfinite(loss):raise ValueError('Nonfinite impulse loss')
        amp.scale(loss).backward();amp.unscale_(opt)
        if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in net.parameters()):
            # update resets unscale bookkeeping; optimizer.step is NOT called.
            amp.update(new_scale=amp.get_scale()/2)
            continue
        norm=nn.utils.clip_grad_norm_(net.parameters(),1.)
        if not torch.isfinite(norm):raise ValueError('Nonfinite FP32 impulse gradient norm')
        amp.step(opt);amp.update();return retry
    raise ValueError('FP16 gradient overflow unresolved after eight scale reductions')


def fit(kind,data,train,validation,directory,experiment_id,max_epochs=25):
    validate_split(data,train,validation)
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    if not torch.cuda.is_available():raise RuntimeError('CUDA required for impulse neural training')
    torch.set_num_threads(2);torch.cuda.set_per_process_memory_fraction(.45)
    identity=dict(experiment_id=experiment_id,kind=kind,seed=SEED,
        data=getattr(data,'identities',['synthetic_test_fixture']),
        train_sha256=hashlib.sha256(np.asarray(train,dtype='int64').tobytes()).hexdigest(),
        validation_sha256=hashlib.sha256(np.asarray(validation,dtype='int64').tobytes()).hexdigest(),
        code_sha256=sha(Path(__file__)))
    ip=directory/'identity.json'
    if ip.exists() and json.loads(ip.read_text())!=identity:raise ValueError('Training identity changed')
    atomic_json(ip,identity)
    mean,std=scale_train(data,train);np.savez(directory/'scaler.npz',mean=mean,std=std)
    torch.manual_seed(SEED);net=ImpulseNet(kind).cuda()
    opt=torch.optim.AdamW(net.parameters(),lr=.001,weight_decay=.01)
    amp=torch.amp.GradScaler('cuda');best=float('inf');stall=0;start_epoch=0;best_weights=None
    checkpoint=directory/'checkpoint.pt'
    if checkpoint.exists():
        saved=torch.load(checkpoint,weights_only=True,map_location='cpu')
        if saved['identity']!=identity:raise ValueError('Checkpoint identity mismatch')
        net.load_state_dict(saved['model']);opt.load_state_dict(saved['optimizer']);amp.load_state_dict(saved['amp'])
        torch.set_rng_state(saved['rng']);torch.cuda.set_rng_state_all(saved['cuda_rng'])
        best,stall,start_epoch,best_weights=saved['best'],saved['stall'],saved['epoch']+1,saved['best_weights']
    for epoch in range(start_epoch,max_epochs):
        if stall>=5:break
        temperature=thermal();net.train();order=np.asarray(train)[torch.randperm(len(train)).numpy()];overflows=0
        for offset in range(0,len(order),256):
            if offset%4096==0:thermal()
            x,y=data.batch(order[offset:offset+256]);z=np.clip((x-mean)/std,-10,10)
            if not np.isfinite(y).all():raise ValueError('Invalid net-return target')
            tx=torch.from_numpy(z).cuda();ty=torch.from_numpy(y*100).cuda()
            overflows+=optimizer_step(net,opt,amp,tx,ty)
        pred=predict(net,data,validation,mean,std)
        total=0.;count=0
        for offset in range(0,len(validation),1024):
            _,y=data.batch(validation[offset:offset+1024])
            total+=float(np.square(pred[offset:offset+len(y)]-y,dtype='float64').sum());count+=y.size
        mse=total/count
        if not np.isfinite(mse):raise ValueError('Invalid early-stopping score')
        if mse<best-1e-10:
            best=mse;stall=0;best_weights={k:v.detach().cpu().clone() for k,v in net.state_dict().items()}
        else:stall+=1
        save_checkpoint(checkpoint,dict(identity=identity,epoch=epoch,best=best,stall=stall,
            model=net.state_dict(),optimizer=opt.state_dict(),amp=amp.state_dict(),best_weights=best_weights,
            rng=torch.get_rng_state(),cuda_rng=torch.cuda.get_rng_state_all()))
        atomic_json(directory/'progress.json',dict(epoch=epoch,validation_mse=mse,best_mse=best,
            stall=stall,temperature=temperature,amp_scale=amp.get_scale(),overflow_retries=overflows,ready=False,financial_evidence=False))
    if best_weights is None:raise ValueError('No finite neural checkpoint')
    net.load_state_dict(best_weights);save_checkpoint(directory/'model.pt',best_weights)
    return net,mean,std
