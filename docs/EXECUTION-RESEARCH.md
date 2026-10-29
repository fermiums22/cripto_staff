# Barrier labels and execution economics

Research only, 2026-10-29. Responds to the supplied discussion about maker-first,
amplitude filters, TP/SL, weak-signal rejection and trade-level cost audit.
No real orders; no automatic promotion; favorable historical numbers are not a goal
that permits changing data or choosing on the final period.

SOLUSDT linear futures, seven days of actual minute trade+volume and mark data,
historical funding. Personal maker/taker rates are freshly read via GET
account/fee-rate into ignored artifacts/execution_fees.json. Do not replace them
with generic VIP table rates. Credentials are never read by the training script.

Four GPU XGBoost classifiers: two TP/SL pairs (.6/.4%, 1/.6%) and two entry modes.
Features: lagged returns, historical range, relative volume, candle range, UTC hour.
Direction follows the previous five-minute change. Labels require TP before SL
within 60 minutes and positive net proceeds; expired/unfilled maker orders label0.
Training first4days, validation next1day, final evaluation last2days. Purge 64
minutes at training boundary. Threshold .5/.65/.8 and amplitude filter on/off give
24 candidates. Select only on validation with >=5 trades; freeze before final test.
This history was inspected previously: the final period is not pristine holdout.
Probabilities are uncalibrated model scores, not guaranteed success frequencies.

Maker approximation: limit at last close offset .01%, reject if crossing the
modeled next-open opposite quote; TTL3min; require trade-through .02%. No favorable
TP on fill candle, stop-first when ambiguous. Market exits include half-spread
.01% and slip .05%; stress slip .1%. There is no historical queue, full book,
latency or partial-fill simulation. Candle penetration does not guarantee a fill.
See [Post-Only](https://www.bybit.com/en/help-center/article/Post-Only-Order) and
[fee-rate API](https://bybit-exchange.github.io/docs/v5/account/fee-rate).

One position, 1x, 90% of $15 cash allocated, current quantity/minimum rules, 20%
loss halt. No increased leverage. Positions are forced closed at horizon or period
end; funding counted after entry. Mark history is retained but there is no full
exchange liquidation engine in this fully funded nominal-exposure experiment.

Outputs (ignored): execution_models.json, execution_research.json,
execution_trades.csv for selected final-period trades. Gross uses modeled fills;
net = gross - fees + funding. quote_pnl_per_unit exposes the pre-fill-friction
reference. MFE/MAE use only fully held interior candles and therefore understate
possible extremes on entry/exit candles; they are not exact tick excursions.
Final charts compare selected ML, higher costs, and same execution without ML or
amplitude filter. Different fills/entries can change trajectories; this is not a
paired cost-only attribution study. CSV includes entry/exit, side, fees, funding,
gross/net PnL, TP/SL, reason, score, MFE/MAE and balance.

Run as codex in CT103: `LD_LIBRARY_PATH=/opt/nvidia-driver .venv/bin/python execution_research.py`.
Input data/execution_history.json must contain the trade volume column. Research
does not change live PAPER models or services.
