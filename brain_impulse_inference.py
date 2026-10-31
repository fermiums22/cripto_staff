"""Causal sequence inference adapter for isolated historical/future PAPER runners.

No training, label lookup, wallet mutation or promotion. Each instance belongs to
one replay/trial; reconnects and gaps discard warmup rather than padding history.
"""
from collections import deque
import numpy as np
from brain_impulse_dataset import ASSETS,HORIZONS,LENGTH,intersects
from brain_impulse_data import FEATURES


class SequenceSignals:
    def __init__(self,predict_batch,uncertainty=None,reservations=()):
        self.predict_batch=predict_batch
        self.uncertainty=np.zeros(8) if uncertainty is None else np.asarray(uncertainty,dtype='float64')
        if self.uncertainty.shape!=(8,) or not np.isfinite(self.uncertainty).all() or np.any(self.uncertainty<0):
            raise ValueError('Invalid per-output uncertainty')
        self.reservations=tuple(reservations);self.history={};self.last={};self.last_global=-1

    def __call__(self,row):
        now=int(row['ts']);symbol=row['symbol']
        if now<self.last_global:raise ValueError('Inference clock regression')
        self.last_global=now
        if symbol not in ASSETS:return []
        if intersects(now-60000,now+180000,self.reservations):
            self.history.pop(symbol,None);self.last.pop(symbol,None);return []
        last=self.last.get(symbol)
        if last and now<=last[0]:raise ValueError('Duplicate or regressing symbol observation')
        if last and (row['session']!=last[1] or now-last[0]>7000):self.history.pop(symbol,None)
        self.last[symbol]=(now,row['session'])
        x=np.asarray(row['x'],dtype='float32')
        if x.shape!=(len(FEATURES),) or not np.isfinite(x).all():raise ValueError('Invalid inference features')
        history=self.history.setdefault(symbol,deque(maxlen=LENGTH));history.append(x.copy())
        if len(history)<LENGTH:return []
        prediction=np.asarray(self.predict_batch(np.asarray(history)[None,:,:]),dtype='float64')
        if prediction.shape!=(1,8) or not np.isfinite(prediction).all():raise ValueError('Invalid net-return prediction')
        return [dict(symbol=symbol,session=row['session'],observed_ms=now,
            horizon_ms=horizon,side=side,expected_net_return=float(prediction[0,2*h+j]),
            uncertainty=float(self.uncertainty[2*h+j]))
            for h,horizon in enumerate(HORIZONS) for j,side in enumerate((1,-1))]


def neural_predictor(net,mean,std,device='cuda'):
    """Match training's scaling and percentage-unit output; net already verified by caller."""
    import torch
    mean=np.array(mean,dtype='float32',copy=True);std=np.array(std,dtype='float32',copy=True)
    if mean.shape!=(len(FEATURES),) or std.shape!=mean.shape or not np.isfinite([mean,std]).all() or np.any(std<=0):
        raise ValueError('Invalid frozen scaler')
    net.to(device);net.eval()
    def predict(x):
        z=np.clip((x-mean)/std,-10,10)
        with torch.no_grad():return net(torch.from_numpy(z).to(device)).float().cpu().numpy()/100
    return predict
