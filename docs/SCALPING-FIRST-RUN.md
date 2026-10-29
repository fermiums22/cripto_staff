# Autonomous minute-data search: first verified run

Run: `20261029T082746Z`, completed 2026-10-29 11:27 Minsk.
Research code revision: `f248234` (later documentation/UI revision `a02dd03`).

Downloaded 90 days of real one-minute Bybit spot candles. Aligned dataset:
129593 candles per symbol for BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT.
Thirty XGBoost models trained on `cuda:0`; 18 configurations compared on validation.
The selected candidate used cross-asset features, TP 1%, SL 0.6%, maximum holding
30 minutes and score threshold 0.5. Only that selected configuration was assessed
on the final period; no second choice was promoted after inspecting the result.

Final-period results, separate $15 virtual accounts:

| Symbol | Net return | Trades | Trades/day | Mean holding, minutes |
|---|---:|---:|---:|---:|
| BTC | -0.237% | 4 | 0.22 | 30.0 |
| ETH | +0.386% | 1 | 0.06 | 30.0 |
| SOL | -3.531% | 29 | 1.61 | 21.8 |
| XRP | +0.816% | 2 | 0.11 | 19.0 |
| DOGE | -2.161% | 6 | 0.33 | 11.8 |

Mean return: -0.946%; double-slippage stress: -1.639%. Candidate rejected.
Single winning trades do not establish profitability. The trade frequency also
does not satisfy an aspiration for frequent scalping. No actual funds, live
model, portfolio balance or Telegram allowlist were changed by this experiment.

The source data is in `data/research.sqlite3`; selected weights and exact results
are in `artifacts/search-runs/20261029T082746Z/`. All are on CT 103, outside Git.
Daily recurring search runs at 03:15 Minsk. News collection repeats every fifteen
minutes. The first news collection succeeded for all three sources: 50 Bybit
announcements, 25 CoinDesk headlines, 20 Federal Reserve releases. Historical
publication dates are preserved separately from first observation time; these
news items were not used retroactively in this training run.

Verified: 22 unit tests, Linux deployment, successful systemd research exit,
active paper/Telegram/dashboard services and both timers, desktop/mobile browser
checks without JavaScript errors or page overflow. Notification delivery logic is
tested with mocked Telegram calls; no fake profitable trades were sent. Each user
must enable notifications independently using `/notify_on` or the keyboard button.
