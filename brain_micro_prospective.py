"""Immutable prospective microstructure PAPER replay; never a live-order interface.

Fixed future observations are evaluated once after the entire reserved window.
This is an intermediate evidence gate, not a substitute for full-depth live PAPER.
"""
import hashlib
import json
import pathlib
import time
import numpy as np
import torch
from brain_research import Net, transform, write
from brain_micro_validation import labelled_samples, compare

SOURCE = pathlib.Path(__file__).resolve().parent
FILES = ("brain_microstructure.py", "brain_micro_validation.py",
         "brain_micro_prospective.py", "brain_research.py")


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def reserve(directory, model, scaler, report, now_ms=None):
    if not report["development_pass"]:
        return None
    now_ms = int(time.time()*1000) if now_ms is None else now_ms
    trials = directory/"prospective-v1"
    trials.mkdir(exist_ok=True)
    # Only one prospective candidate per protocol family, avoiding repeated testing.
    if list(trials.glob("*/protocol.json")):
        return None
    trial = trials/str(now_ms)
    trial.mkdir()
    for source, name in ((model, "model.pt"), (scaler, "scaler.npz")):
        (trial/name).write_bytes(source.read_bytes())
    start = ((now_ms//86400000)+1)*86400000
    protocol = dict(version=1, created_ms=now_ms, future_start_ms=start,
        future_end_ms=start+14*86400000, fee=.0006, slip=.0003,
        mode="prospective PAPER replay, public receive-time observations only",
        source_hashes={f: sha(SOURCE/f) for f in FILES},
        artifact_hashes={f: sha(trial/f) for f in ("model.pt", "scaler.npz")},
        selection=report, ready=False)
    write(trial/"protocol.json", protocol)
    write(trial/"frozen.json", dict(protocol_sha256=sha(trial/"protocol.json")))
    return str(trial)


def verify(trial):
    p = json.loads((trial/"protocol.json").read_text())
    frozen = json.loads((trial/"frozen.json").read_text())
    if sha(trial/"protocol.json") != frozen["protocol_sha256"]:
        raise ValueError("prospective protocol modified")
    for f, expected in p["source_hashes"].items():
        if sha(SOURCE/f) != expected:
            raise ValueError("prospective source changed; keep trial invalid, do not re-freeze")
    for f, expected in p["artifact_hashes"].items():
        if sha(trial/f) != expected:
            raise ValueError("prospective artifact changed")
    return p


def evaluate_due(directory, d, now_ms=None):
    now_ms = int(time.time()*1000) if now_ms is None else now_ms
    for trial in sorted((directory/"prospective-v1").glob("*")):
        if not (trial/"frozen.json").exists() or (trial/"result.json").exists():
            continue
        try:
            p = verify(trial)
            if now_ms < p["future_end_ms"]+600000:
                continue
            ix = ((d["ts"] >= p["future_start_ms"]) & (d["ts"] < p["future_end_ms"]))
            future = {k: v[ix] for k, v in d.items()}
            x, y, ts = labelled_samples(future, p["fee"], p["slip"])
            if not len(ts):
                result = dict(ready=False, statistical_pass=False, reason="No usable future samples")
            else:
                with np.load(trial/"scaler.npz") as scale:
                    z = transform(x, scale["mean"], scale["std"])
                net = Net()
                net.load_state_dict(torch.load(trial/"model.pt", weights_only=True, map_location="cpu"))
                net.eval()
                with torch.no_grad():
                    pred = net(torch.from_numpy(z)).numpy()/100
                result = compare(pred, x, y, ts)
                # Require observations across all fourteen reserved days.
                observed_days = len(np.unique(ts//86400000))
                hours = len(np.unique(ts//3600000))
                result.update(observed_days=observed_days, observed_hours=hours,
                    statistical_pass=bool(result["development_pass"] and
                                          observed_days == 14 and hours >= 320),
                    ready=False, samples=len(ts),
                    next_action="Full-depth live PAPER needed; this replay cannot establish execution readiness")
            result.update(protocol_sha256=sha(trial/"protocol.json"), evaluated_ms=now_ms)
            write(trial/"result.json", result)
        except Exception as exc:
            write(trial/"blocked.json", dict(ready=False, reason=str(exc), checked_ms=now_ms))
