# Published bots: initial reproducible experiments

Sources checked 2026-10-29. These projects contain real implementations; no
verified profitability claim follows from their existence or popularity.

## Sources reviewed

- [Hummingbot controllers](https://hummingbot.org/strategies/v2-strategies/controllers/): reusable directional and market-making implementations.
- [Bollinger V1 source](https://github.com/hummingbot/hummingbot/blob/master/controllers/directional_trading/bollinger_v1.py): 3m, BB100, two standard deviations; long below lower band.
- [MACD BB source](https://github.com/hummingbot/hummingbot/blob/master/controllers/directional_trading/macd_bb_v1.py): adds MACD21/42/9; long when MACD negative and histogram positive.
- [Freqtrade Quickie](https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/berlinguyinca/Quickie.py): examined momentum example, not deployed; 5m ADX/TEMA conditions and time-varying ROI differ from our executor.
- [Freqtrade lookahead analysis](https://www.freqtrade.io/en/stable/lookahead-analysis/): motivates prefix-invariance and next-bar-entry checks. Freqtrade itself was not installed or run.

## Implemented adaptations, not original bot performance

`sourced_rules.py` independently implements the two Hummingbot long entry ideas.
BB uses population standard deviation; EMA is seeded from the first close with
200-candle warmup. These numerical details can differ from pandas_ta. Historical
features use complete UTC-aligned 3-minute candles; execution uses minute candles.
Live uses the last 300 closed 3-minute candles, refreshed approximately every
30 seconds. Only a fresh, unused completed-candle signal can open a position.

Local execution assumptions deliberately differ from full Hummingbot: spot long
only, one position per strategy, independent $15, TP1%/SL2%, no timer, 20% loss
halt, taker fee .1% and slip .05% per side. No short, leverage, funding, maker
queue, Hummingbot executors or trailing stop. A candle below the band is not a
guarantee of reversal. Quote polling/network delays can worsen exits.

`sourced_research.py` runs the first 20 days and last 10 days separately with base
spread .02% and stress .06%. It does not tune parameters or choose a winner.
History was already examined by other experiments; this is not pristine holdout.
Terminal positions are liquidated and included in PnL; ambiguous candles use
stop first. Current lot rules and assumed depth limit interpretation.

`hb_bollinger` and `hb_macdbb` are explicitly authorized exploratory PAPER
accounts, not promoted profitable models. Their histories persist across restarts
and Telegram pause/notifications apply. Retired earlier variants remain retired.
The dashboard shows their historical curves separately from live account equity.

Run on CT103 as codex: `.venv/bin/python sourced_research.py`.
Read-only input: data/research.sqlite3. Output: artifacts/sourced_research.json.
No exchange credential or order API is used by these experiments.
