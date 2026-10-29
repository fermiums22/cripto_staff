# Historical experiment: opposite windows

User approved on 2026-10-29: leverage 10x, SL 10% of price, basket target covering
losses and expenses plus .1% of active entry notional; add the opposite side after
30 minutes without closing, subject to margin. Initial direction is pseudorandom.
Historical test only for this run; no real orders or new live strategy.

Explicit additional assumptions: SOLUSDT perpetual, seven days, initial $10,
up to $2 initial margin per window, maximum four windows (a test cap, not a claim
that all cash is exhausted). Quantities are floored to current lot rules; effective
margin can be below $2. Market taker fee .1% per side was verified using the
account's read-only fee endpoint for SOLUSDT. Spread .02%, slip .05% per side are
assumptions, not measured historical execution. Stress: spread .06%, slip .1%.

The margin model is approximate cross margin without hedge discounts. It sums
current lowest-tier maintenance requirements, includes an exit-fee reserve, and
checks the adverse mark-price extreme before beneficial exits. A liquidation
terminates that run and floors remaining balance at zero. This is not a replica
of Bybit's tier reduction, insurance/ADL or matching engine. Independent virtual
windows differ from exchange aggregation of same-side positions. Source data:

- [Trade candles](https://bybit-exchange.github.io/docs/v5/market/kline)
- [Mark candles](https://bybit-exchange.github.io/docs/v5/market/mark-kline)
- [Funding history](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate)
- [Current risk tiers](https://bybit-exchange.github.io/docs/v5/market/risk-limit)
- [Liquidation modes](https://www.bybit.com/en/help-center/article/UTA-Trading-Rules-Liquidation-Process)

Funding applies to existing positions at the settlement timestamp. Net funding
can be zero for matched opposite quantities; zero does not mean funding was
omitted. Target uses total net liquidation equity, including entry/exit fees,
funding and any previously realized stops. The profit anchor rises only after a
successful basket close. Minute-close target checks are conservative relative
to an intraminute trigger; minute OHLC cannot reconstruct full event ordering.
All remaining positions are closed for the terminal report, never hidden.

Seeds 0 and 1 give opposite initial directions. More seeds do not add independent
evidence here: after initial direction, additions alternate deterministically.
Results are exploratory, not optimized or a forecast.

Run `python window_experiment.py`. Cached public history is in
data/window_history.json (reused for an hour); report is
artifacts/window_experiment.json. Both ignored by Git. Dashboard shows two equity
curves and stress results. Unit tests cover flat-price losses, bounded windows,
funding, mark-triggered liquidation, terminal accounting and hedge neutrality.

Initial result: long-first 9.890755 USDT (-1.09245%), short-first 9.846755 USDT
(-1.53245%). Each opened four windows, no basket targets, stops or liquidations;
all four were still open at period end. Commissions about .082028 USDT each run;
net funding zero. Matching opposite exposure largely froze price PnL rather than
making either direction profitable. Window cap prevented further additions.
