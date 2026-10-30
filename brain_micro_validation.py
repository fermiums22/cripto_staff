"""Development-only microstructure labels and conservative selection.
Never reads credentials or sends orders. No changes to the frozen 15m trial.
"""
import numpy as np


def labelled_samples(d, fee, slip):
    """Long-only 120s labels, delayed entry, no reconnect or missing-sample bridges."""
    xs, ys, times = [], [], []
    for symbol in np.unique(d["symbols"]):
        for session in np.unique(d["sessions"][d["symbols"] == symbol]):
            ix = np.where((d["symbols"] == symbol) & (d["sessions"] == session))[0]
            ix = ix[np.argsort(d["ts"][ix], kind="stable")]
            ts = d["ts"][ix]
            for local, i in enumerate(ix):
                entry = np.searchsorted(ts, ts[local] + 1000)
                end = np.searchsorted(ts, ts[local] + 120000)
                if end >= len(ix) or entry >= len(ix):
                    continue
                if ts[end]-ts[local] > 126000 or ts[entry]-ts[local] > 7000:
                    continue
                if np.any(np.diff(ts[local:end+1]) > 7000):
                    continue
                ei, zi = ix[entry], ix[end]
                if min(d["depth"][ei], d["depth"][zi]) < 60:
                    continue
                # Exclude every hourly boundary, covering hourly and multi-hour funding.
                if ts[local]//3600000 != ts[end]//3600000:
                    continue
                values = np.r_[d["x"][i], d["ask"][ei], d["bid"][zi]]
                if not np.isfinite(values).all() or min(values[-2:]) <= 0:
                    continue
                xs.append(d["x"][i])
                ys.append(d["bid"][zi]/d["ask"][ei]-1-2*(fee+slip))
                times.append(ts[local])
    if not times:
        return np.empty((0, 8), dtype="float32"), np.empty(0), np.empty(0, dtype="int64")
    order = np.argsort(times, kind="stable")
    return (np.asarray(xs, dtype="float32")[order],
            np.asarray(ys, dtype="float32")[order], np.asarray(times)[order])


def wallet_returns(scores, y, ts, threshold):
    """Single shared diagnostic wallet; deterministic first signal wins ties."""
    pnl = np.zeros(len(ts))
    next_ms = 0
    for j, stamp in enumerate(ts):
        if stamp < next_ms or not np.isfinite(scores[j]) or scores[j] <= threshold:
            continue
        pnl[j] = y[j]
        next_ms = stamp + 126000
    return pnl


def compare(pred, raw_x, y, ts):
    """Fixed controls on the same validation dates, without threshold search."""
    rules = {"candidate": (pred, .001), "momentum": (raw_x[:, 2], .003),
             "reversal": (-raw_x[:, 2], .003), "cash": (np.zeros(len(ts)), 1.)}
    returns = {name: wallet_returns(score, y, ts, threshold)
               for name, (score, threshold) in rules.items()}
    days = np.arange(ts[0]//86400000, ts[-1]//86400000+1)
    daily = {k: np.array([v[ts//86400000 == day].sum() for day in days])
             for k, v in returns.items()}
    rng = np.random.default_rng(712)
    ids = rng.integers(0, len(days), (4000, len(days)))
    lower = {k: float(np.quantile((daily["candidate"]-v)[ids].mean(axis=1), .0125))
             for k, v in daily.items() if k != "candidate"}
    reports = {}
    for name, pnl in returns.items():
        eq = np.cumprod(1+pnl)
        peak = np.maximum.accumulate(np.r_[1., eq])[1:]
        active = pnl != 0
        reports[name] = dict(net_return=float(eq[-1]-1),
            closed_trade_drawdown=float(np.max(1-eq/peak)), trades=int(active.sum()),
            stress_net_return=float(np.prod(1+pnl-active*.001)-1))
    c = reports["candidate"]
    passed = (len(days) >= 7 and c["trades"] >= 100 and c["net_return"] > 0
              and c["stress_net_return"] > 0 and c["closed_trade_drawdown"] <= .10
              and all(v > 0 for v in lower.values()))
    return dict(controls=reports, paired_daily_lower_bounds=lower,
                validation_days=len(days), development_pass=bool(passed), ready=False,
                limitations=["Top-of-book proxy, not full depth execution.",
                             "Closed-trade drawdown omits intratrade losses.",
                             "Independent future PAPER and execution audit still required."])
