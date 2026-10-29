# Random long/short with tighter brackets

Historical test requested 2026-10-29. Uses cached seven-day SOLUSDT perpetual
trade/mark/funding history from window_experiment.py. Initial $10, leverage10,
25% remaining wallet initial margin per position; no concurrent hedge windows.
After exit, next entry is the next minute open with pseudorandom long/short.

Fixed grid before evaluation: TP .3%/.6%/1%; SL .1%/.3%/.6%, all price distances.
First five days rank nine configurations by mean result over seeds0–4. Last two
days evaluate with seeds100–104; select nothing using these results. Previously
examined history is not pristine holdout. No profitability threshold is relaxed.

Taker fee .1% per side, assumed spread .02% and slippage .05% per side. Stress
spread .06%, slip .1%. Current lot/minimums/MMR. Historical funding, adverse
mark-extreme liquidation proxy, stop-first OHLC and explicit terminal close.
Small balances may stop trading because lot/minimum requirements become
unaffordable; the approximately -60% plateaus are not a protective loss limit.
Single-position cross-margin approximation, not exact exchange risk engine.
Minute candles cannot determine intraminute stop/target ordering or fills.

`python random_brackets.py` writes artifacts/random_brackets.json. The dashboard
shows all nine rows and the selected configuration's five evaluation curves.
No live bot or orders are enabled by this experiment.

Result: selected TP1%/SL.6% returned mean -29.94% in selection and -13.03% in
evaluation (range -20.22% to -7.76%). Stress mean -22.63%. None of the nine
configurations had a profitable evaluation seed among those tested. This rejects
this grid on this sample; it does not prove all possible strategies unprofitable.
