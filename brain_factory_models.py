"""Small causal sequence competitors. Inputs are closed historical bars only."""
import torch
from torch import nn


class SequenceModel(nn.Module):
    def __init__(self, kind, symbols=6, features=8, width=32, length=16):
        super().__init__()
        self.kind, self.symbols = kind, symbols
        inputs = symbols * features
        self.embed = nn.Linear(inputs, width)
        self.head = nn.Linear(width, symbols)
        if kind == "transformer":
            self.position = nn.Parameter(torch.zeros(1, length, width))
            layer = nn.TransformerEncoderLayer(width, 4, width*2, dropout=0.,
                                               batch_first=True)
            self.encoder = nn.TransformerEncoder(layer, 2, enable_nested_tensor=False)
        elif kind in ("gru", "lstm"):
            self.encoder = (nn.GRU if kind == "gru" else nn.LSTM)(
                width, width, batch_first=True)
        elif kind == "tcn":
            self.encoder = nn.Sequential(nn.Conv1d(width,width,3,dilation=1),nn.SiLU(),
                                         nn.Conv1d(width,width,3,dilation=2),nn.SiLU())
        elif kind == "moe":
            self.experts = nn.ModuleList([nn.Sequential(nn.Linear(width,width),nn.SiLU(),
                                           nn.Linear(width,symbols)) for _ in range(3)])
            self.gate = nn.Linear(width,3)
        elif kind == "mlp":
            self.encoder = nn.Sequential(nn.Linear(length*width,width),nn.SiLU())
        else:
            raise ValueError(kind)

    def forward(self, x):
        h = self.embed(x.flatten(2))
        if self.kind == "transformer":
            # Causal temporal attention; each token includes all markets at that time.
            mask = torch.triu(torch.ones(h.shape[1],h.shape[1],device=h.device,
                                        dtype=torch.bool),diagonal=1)
            h = self.encoder(h+self.position[:,:h.shape[1]],mask=mask)[:,-1]
        elif self.kind in ("gru", "lstm"):
            # cuDNN RNNs use fp32 here; projection/head still benefit from AMP.
            with torch.autocast(device_type=h.device.type, enabled=False):
                h = self.encoder(h.float())[0][:,-1]
        elif self.kind == "tcn":
            h = self.encoder(h.transpose(1,2))[:,:,-1]
        elif self.kind == "moe":
            h = h.mean(1)
            weights = self.gate(h).softmax(-1)
            return (torch.stack([e(h) for e in self.experts],-1)*weights[:,None,:]).sum(-1)
        else:
            h = self.encoder(h.flatten(1))
        return self.head(h)
