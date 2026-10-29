# Shared-capital research challenge

Implemented separately from the existing arena. No account credentials or real
orders are used. The dashboard section is **«Битва за $40 000»**.

## Universe and timestamps

`portfolio_market.py` paginates all currently trading USDT perpetual instruments,
then records quotes, spread, 24-hour turnover, funding, OI, mark/index basis,
listing time and movement since the preceding snapshot. Stock, ETF and commodity
contract types are excluded from cryptocurrency eligibility. Current eligibility:
turnover >= $3m/day, quoted full spread <= 0.1%. New listings are flagged.

Historical resource cohort: the 20 highest-turnover eligible cryptocurrencies at
collection time, plus BTC/ETH if absent. It is **not** a historical whole-market
universe. Delisted coins and past constituents are not recovered. Using today's
liquid survivors introduces selection/survivorship bias; a positive result here
is exploratory, not proof of a deployable profitable strategy.

Collected 90 days of public 15-minute trade OHLCV/turnover, mark OHLC and paginated
funding history. Timestamps must align exactly. Gaps and insufficient listing
history exclude a coin with a recorded reason, never invent candles. Current
instrument lot/tick/minimum/risk rules are frozen with the data; historical rule
changes and historical spread are not known. This is not second-level scalping.

Future recording: `portfolio_stream.py`, `cripto-market-stream.service`, public
linear WebSocket. Five symbols include BTC/ETH and eligible movers; refreshed
every five minutes. Raw book snapshots/deltas, public trades, ticker updates
(including OI/mark/index/funding fields when published), liquidation messages,
exchange timestamps, local receipt timestamps and session IDs are stored.
Reconnect/session boundaries are explicit gaps, not uninterrupted coverage.
No liquidation event is fabricated if no such message arrives.

Compressed recordings are capped around 200 MiB by deleting oldest completed
session files; reserve 512 MiB disk, 50% CPU and 256 MiB RAM. This is a bounded
rolling archive, not indefinite retention. Files are private project artifacts.
Current snapshots/streams are **not fed backwards into historical training**.
Existing news collection remains separate until timestamped feature coverage and
an ablation test exist. No fabricated historical order-flow, OI or news features.

## Learned models

`portfolio_research.py`: first 45 days train, next 15 select, last 30 test frozen
models and policies. No threshold or risk selection on the last 30 days.
Feature normalization uses training data only. Four-bar forecast labels end
before selection begins. Full source, inputs, hashes, weights, normalization,
selection, test reports and trade CSVs live in `artifacts/portfolio/<UTC>/`.

Compact sequence Mixture of Experts has three genuinely trained GRU encoders:
own price/volume/volatility sequence, BTC/ETH/correlation/relative-strength
sequence, and funding/mark-trade basis. A trained gate dynamically weights their
forecasts. Sequence length 16 bars, forecast horizon four bars; eight epochs,
seed 42, up to 60,000 training examples. Checkpoint and measured weight change
are saved. The compact network uses the installed CPU PyTorch to avoid adding
another multi-gigabyte CUDA stack to the small container. CUDA is used for the
XGBoost competitor and verified from its training configuration.

Models forecast return amplitude, not calibrated TP probabilities. Entry requires
absolute forecast >= 0.6%; allocation ranks forecasts against past volatility.
Forecast, selection reason and per-position contribution are recorded.
Reported neural gate weights describe routing, not causal feature importance.
XGBoost gain importance is also saved; this is not a held-out permutation study.

Momentum and cross-asset lag rules are additional explicit benchmarks, plus cash.
The older PPO result uses a different data interval and accounting environment:
it remains visible separately and is not misleadingly ranked in this comparison.
Shared multi-asset RL, a GPU sequence runtime, maker-first paired execution, a
trained strategy-switching allocator and causal feature ablations remain future
extensions. The current Portfolio Allocation Agent is a constrained deterministic
allocator driven by learned forecasts, **not a separately trained RL allocator**.

## One $15 wallet

`portfolio_sim.py` compares SOL-only, best-coin concentration and up-to-three-coin
allocation. Each trial has one total $15 wallet; coins do not receive independent
deposits. Leverage scenarios: 1x, 3x and 10x. No account reset within the continuous
30-day test; additional three 10-day trials are separately labelled $15 trials.

Only closed bars inform decisions; fills use the next open, adverse tick rounding,
0.06% per-fill friction, with 0.16% stress. Taker fee is a uniform scenario based
on the observed SOL account rate, **not a verified per-symbol fee schedule**.
Fees apply to the full notional. Budget includes margin and entry fee; quantities
round down to lot steps and obey minimum quantity/notional, maximum quantity,
first risk-tier notional and allowed leverage. Unaffordable orders are rejected.
If splitting would violate minima, reduce the number of selected coins.

The allocator uses past turnover, rejects a >5% past-hour move (pump-chasing
filter), and blocks new same-exposure pairs with rolling return correlation
above 0.75. This is a risk constraint, not a guarantee of diversification.
Existing positions hold at least one hour before opposite-signal exits, and
normally close after four hours. Free capital is redistributed on hourly checks;
unrealized profit is not spent as free cash. No averaging down or artificial refill.

Isolated margin only, no automatic margin top-up. Funding debits free cash first,
then isolated margin; positive funding credits cash. Mark opening gaps are checked
before discretionary exits and adverse mark OHLC before bar-close valuation.
Maintenance uses the frozen first risk tier and closing fee. Liquidation is a
conservative OHLC proxy: adverse-extreme fill, isolated bankruptcy cap and explicit
bankruptcy adjustment. It does **not** reproduce exchange partial liquidations,
insurance fund, funding-event intra-bar microstructure or future risk-tier changes.
All surviving positions close with fees at the final boundary.

Every run reconciles final wallet to $15 plus the net trade ledger. Reports retain
near-total losses and liquidation counts. Near-zero dust is not silently relabelled
as an exact zero balance. Ruin probability is not inferred from these few periods.

## Commands and checks

Follow `SERVER.md`; run as codex with direct internet and project venv:

```sh
.venv/bin/pip install -r requirements-portfolio.txt
.venv/bin/python portfolio_market.py --days 90
LD_LIBRARY_PATH=/opt/nvidia-driver .venv/bin/python portfolio_research.py
.venv/bin/python -m unittest discover -s tests -p test_portfolio.py
```

Research is a bounded one-off unit (2 CPUs, 3 GiB RAM, 30-minute maximum), not an
unlimited self-modifying process. Only the public recorder runs continuously.
Old paper services, Telegram, Nika and old experiments are preserved.

Sources: [instruments and pagination](https://bybit-exchange.github.io/docs/v5/market/instrument),
[risk tiers](https://bybit-exchange.github.io/docs/v5/market/risk-limit),
[book snapshot/delta protocol](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook),
[public trades](https://bybit-exchange.github.io/docs/v5/websocket/public/trade),
[liquidation stream](https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation).

## Frozen-result audit (2026-10-29)

`portfolio_audit.py` loads the original run's history hashes and XGBoost weights;
it does not refit or select models. Base/stress balances, fees, trade count and
drawdown must exactly reproduce the saved report before attribution is published.
`portfolio_sim.py` now records the positions/cash/peak at maximum drawdown without
changing baseline calculations. Audit JSON and stress CSV are kept with the run;
the dashboard has a separate audit panel.

For run `20261029T144303Z`, selected `xgb_multi_1x`:

- Net +2.501760865 USDT. QUSDT contributed +7.920407399 (49 trades),
  1000PEPEUSDT +1.451977900; INITUSDT lost 5.505309692 over four trades.
- Reference-price gross +5.7607; modeled fill friction/tick rounding 1.30235;
  commissions 1.94131233; funding is accounted separately. Thus commissions are
  not the only cost, and aggregate returns conceal substantial coin concentration.
- Removing the three best recorded profits arithmetically gives net -2.468774422.
  That subtraction is not a realizable replay. A separate actual frozen-policy
  replay prohibiting Q entries and redistributing capital returns -38.548684%.
- The adverse mark-envelope drawdown is 35.899632%, on the bar starting
  2026-10-18 10:45 UTC, with a QUSDT long open. Peak equity 16.007539079;
  adverse equity 10.260891383. Drawdown on the stored downsampled close curve is
  32.403873%, not a replacement for the intrabar risk measure.
- Stress preserves all 81 entry identities and all exit times, changes sizes in
  64 trades. Repricing fixed base quantities/times adds 1.93457373 in direct costs;
  full replay resizing reduces capital another 0.252135701. The fee rate is
  unchanged: the stress increases per-fill friction from .06% to .16%.
- Holding-limit diagnostics: 2h -14.957156%, original 4h +16.678406%,
  8h -4.999293%, 16h -65.275444%. Opposite-signal exits still apply.
  These are post-hoc sensitivities on an already seen test, not independent
  selection results and not new promoted strategies.

No Ranker/RL allocator was added during attribution. The positive result remains
dependent on the current-survivor cohort and a concentrated set of outcomes.
The scanner now archives its first observed UTC snapshot each day under
`data/universe_snapshots/`, including instrument definitions and observation time.
This archive starts now; it does not reconstruct delisted instruments from the
previous three months and must never be presented as if it did.
