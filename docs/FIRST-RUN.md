# First verified run — 2026-10-29

Code revision: `b2dc6c5`. Container: 103 (`codex-home`).
Source: real Bybit spot candles, fetched directly without a process proxy.
8639 closed five-minute candles per symbol, BTCUSDT/ETHUSDT/SOLUSDT.

Twelve XGBoost fits completed on `cuda:0`: three chronological validation fits
and one final paper model per symbol. CPU fallback is rejected in code. Training
uses the RTX 5070; live inference uses CPU. GPU need not stay busy between fits.
`requirements.lock` records the resolved Linux Python environment.

Historical net returns after assumed costs (each cell starts with a separate $15):

| Symbol | Window 1 | Window 2 | Window 3 | Total closed trades |
|---|---:|---:|---:|---:|
| BTCUSDT | 0.000% | 0.000% | 0.000% | 0 |
| ETHUSDT | 0.000% | -0.456% | -1.122% | 3 |
| SOLUSDT | -0.947% | +0.043% | -0.153% | 8 |

There is no demonstrated profitable strategy. BTC's zero return reflects no
entries at the fixed 0.60 threshold, not successful trading. The sample is too
small for a profitability conclusion. These are research results, not live PnL.
Full timestamps, baselines, drawdowns and assumptions are recorded on the server
in `artifacts/research.json`. Models and raw data are retained there, outside Git.

`cripto-paper.service` was enabled and started. Initial live paper equity: $15,
no position, no real orders. A real service restart produced a new heartbeat,
preserved the portfolio, and reported no error. Nine unit tests passed both on
Windows and in the Linux container. Synthetic unit-test fixtures are not used
for model training or performance reports.

Read status from Windows with `powershell -ExecutionPolicy Bypass -File .\status.ps1`. This is a status
command, not a dashboard. If heartbeat age exceeds 120 seconds, investigate the
service and connectivity; an old $15 snapshot is not proof of a working agent.

Still missing from the full project brief: calibrated and independently selected
profitable strategies, longer/regime-diverse tests, cross-asset signals, order-book
data, reinforcement learning comparisons, derivatives simulation, controlled
retraining and a dashboard. Read-only account integration is also not implemented.
