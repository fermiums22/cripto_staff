"""Research admission and purged walk-forward policy; never authorizes orders.

The evidence registry is immutable. A test interval cannot become development
data merely because a previous model failed on it.
"""
from dataclasses import dataclass
import numpy as np


DAY = 86400000


@dataclass(frozen=True)
class ResearchPolicy:
    minimum_development_days: int = 21
    minimum_hours_per_day: int = 20
    minimum_minutes_per_hour: int = 45
    minimum_symbols: int = 4
    train_days: int = 7
    validation_days: int = 7
    evaluation_days: int = 7
    purge_ms: int = 180000
    max_drawdown: float = .10
    max_notional: float = 12.
    initial_equity: float = 15.
    max_exposure: float = 1.


def development_mask(signal_ms, exit_ms, reserved):
    """Conservative closed-interval intersection; purge a full label, not just its start."""
    signal_ms, exit_ms = np.asarray(signal_ms), np.asarray(exit_ms)
    if signal_ms.shape != exit_ms.shape or np.any(exit_ms < signal_ms):
        raise ValueError('Invalid label intervals')
    keep = np.ones(len(signal_ms), dtype=bool)
    for start, end in reserved:
        if end <= start:
            raise ValueError('Invalid reservation')
        keep &= (exit_ms < start) | (signal_ms >= end)
    return keep


def coverage(rows, policy=ResearchPolicy()):
    """Require per-symbol coverage; a burst of thousands of ticks is not a full hour."""
    bins = {}
    for row in rows:
        stamp = int(row['ts'])
        bins.setdefault((row['symbol'], stamp//3600000), set()).add(stamp//60000)
    hours_by_day = {}
    for (symbol, hour), minutes in bins.items():
        if len(minutes) >= policy.minimum_minutes_per_hour:
            hours_by_day.setdefault((symbol, hour//24), set()).add(hour)
    symbols_by_day = {}
    for (symbol, day), hours in hours_by_day.items():
        if len(hours) >= policy.minimum_hours_per_day:
            symbols_by_day.setdefault(day, set()).add(symbol)
    qualified = sorted(day for day, symbols in symbols_by_day.items()
                       if len(symbols) >= policy.minimum_symbols)
    # Walk-forward requires contiguous market days, not a week scattered over months.
    best, streak, previous = 0, 0, None
    for day in qualified:
        streak = streak+1 if previous is not None and day == previous+1 else 1
        best = max(best, streak); previous = day
    return dict(qualified_days=len(qualified), longest_contiguous_days=best,
                required_days=policy.minimum_development_days,
                admission=best >= policy.minimum_development_days,
                ready=False)


def walk_forward(signal_ms, exit_ms, start_ms, policy=ResearchPolicy()):
    """Expanding training, separate early stopping and diagnostic evaluation blocks.

    Final prospective data must be removed with development_mask BEFORE calling.
    Purge both label endpoints and trailing feature lookback around boundaries.
    """
    ts, end = np.asarray(signal_ms), np.asarray(exit_ms)
    if not len(ts) or np.any(end < ts) or np.any(np.diff(ts) < 0):
        raise ValueError('Invalid chronological labels')
    boundary = start_ms+policy.train_days*DAY
    folds = []
    while boundary+(policy.validation_days+policy.evaluation_days)*DAY <= end[-1]:
        valid_end = boundary+policy.validation_days*DAY
        eval_end = valid_end+policy.evaluation_days*DAY
        train = np.where((ts >= start_ms) & (end < boundary-policy.purge_ms))[0]
        valid = np.where((ts >= boundary+policy.purge_ms) & (end < valid_end-policy.purge_ms))[0]
        test = np.where((ts >= valid_end+policy.purge_ms) & (end < eval_end))[0]
        if min(len(train),len(valid),len(test)):
            folds.append((train,valid,test))
        boundary += policy.evaluation_days*DAY
    return folds


def trade_report(trades, start_ms, end_ms, initial_equity=15., seed=7301):
    """All calendar days, including no-trade days, enter day-block bootstrap CIs.

    Requires a separate event-level mark-to-market audit before acceptance: this
    function intentionally labels its drawdown as closed-trade drawdown only.
    """
    if end_ms <= start_ms:
        raise ValueError('Empty evaluation interval')
    days = np.arange(start_ms//DAY, (end_ms-1)//DAY+1)
    daily = np.zeros(len(days)); equity=initial_equity; peak=equity; dd=0.
    by_symbol = {}; fees=0.
    for row in sorted(trades,key=lambda r:r['closed_ms']):
        if not start_ms <= row['closed_ms'] < end_ms:
            raise ValueError('Trade outside evaluation interval')
        pnl, cost = float(row['net_pnl']),float(row['fees'])
        if not np.isfinite([pnl,cost]).all() or cost < 0:
            raise ValueError('Invalid trade accounting')
        equity+=pnl;peak=max(peak,equity);dd=max(dd,1-equity/peak);fees+=cost
        daily[row['closed_ms']//DAY-days[0]]+=pnl
        symbol=by_symbol.setdefault(row['symbol'],dict(trades=0,net_pnl=0.))
        symbol['trades']+=1;symbol['net_pnl']+=pnl
    rng=np.random.default_rng(seed)
    means=rng.choice(daily,size=(10000,len(days)),replace=True).mean(axis=1)
    lower,upper=np.quantile(means,[.025,.975])
    # Removing the best coin exposes concentration; this is a diagnostic, not a pass by itself.
    without_best=equity-initial_equity-max([v['net_pnl'] for v in by_symbol.values()],default=0.)
    return dict(net_pnl=equity-initial_equity,net_return=equity/initial_equity-1,
        closed_trade_drawdown=dd,trades=len(trades),fees=fees,by_symbol=by_symbol,
        daily_pnl=daily.tolist(),mean_daily_95ci=[float(lower),float(upper)],
        pnl_without_best_symbol=without_best,ready=False)
