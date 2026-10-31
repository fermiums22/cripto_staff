# Market Brain evidence workflow — 2026-10-30

User authorizes autonomous research, implementation, GPU training and PAPER only.
No real orders, no resetting wallets, no changes to HA/Nika/TrueNAS/VPN.
Notify owner only for a genuine permission blocker or verified final result.

## Current facts
- RTX 5070 CUDA verified: torch 2.11.0+cu128; temperature 68 C during initial inspection.
- Prior market_brain_evaluated.py stopped itself at stall 60/step 1440. Its checkpoint and logs are preserved.
- Prior transformer used global volume normalization and contaminated validation. Do not treat its metrics as independent evidence.
- New seed 17/53 MLPs trained on GPU from scratch with train-only scaling, chronological purge, fixed simple baselines.
- Development history was already inspected by earlier work. ALL historical results remain diagnostic.
- No qualified candidate found. Best sufficiently active historical candidate was momentum threshold .008:
  validation -8.411%, stressed -21.339%; later diagnostic -3.280%. It is REJECTED.
- Candidate slot stays CASH. Momentum/reversal are separate experimental control wallets, NOT approved trading strategies.
- Current future protocol: /home/codex/projects/market-brain-storage/evidence-v1/run-20261030-c/protocol.json.
  a/b are preserved staging runs; c reuses b model weights and only fixes absent global control semantics before future data.
- Freeze verifies model/scaler/code SHA256; modifying brain_research.py, brain_forward.py or motivation_core.py halts that trial.
  For corrections, preserve the old run and declare a new future trial. Never quietly update frozen hashes after seeing outcomes.
- 119 tests passed, including temporal causality, next-open alignment, depth/minimums, fees, stale quotes, protocol mutation,
  public-endpoint restriction, book snapshots/deltas/session reset, pause-error handling. Expected mocked Telegram error log occurs in tests.
- Existing adaptive/paper/telegram/dashboard/market-stream units active, not restarted or modified by this work.

## Processes and durability
- brain_supervisor.py supervises isolated brain_channels.py and brain_forward.py.
- User crontab line tagged market-brain-evidence-v1 starts singleton supervisor every minute; prior entries retained.
- Launcher: /bin/sh /home/codex/workspace/cripto_staff/deploy/brain-supervisor.sh.
- State: /home/codex/projects/market-brain-storage/evidence-v1/supervisor.json.
- Logs: same directory, channels.log / forward.log / micro.log / supervisor.log.
- All new output/checkpoints/raw streams persist on existing mounted storage; no new mounts or NAS changes.
- Locks are under project data; atomic JSON replace+fsync avoids partial snapshots.
- Existing global PAPER pause is honored; missing control row means unpaused as in adaptive_live. Database errors fail closed.
- Supervisor reruns microstructure research once daily. Collection continues during training.
- Separate ChatGPT continuation automation runs every six hours, with notifications only for a blocker or verified result.
  Future scheduled tool availability is not guaranteed; inspect actual runs rather than assuming execution.

## New modules
- brain_research.py: reproducible 15m development, ridge/MLP/momentum/reversal/cash, train-only scalers and purged boundaries,
  after-cost diagnostic selection, immutable manifests, no promotion. Trains two small MLPs on GPU; deliberately bounded.
- brain_forward.py: public GET only; timestamped forecasts; observed bid/ask depth fills AFTER >=1s latency,
  fees/slippage/minimums, 1x $15 wallets with max $12 notional, 1% stop checked every ~5s, 10% equity drawdown halt.
  It is a coarse 15m research engine, NOT a subsecond impulse-entry engine.
  Exit book consumed only after trigger; slippage per side .0003, fee per side .0006 are conservative scenarios.
  Funding charges use max observed mark bound; credits ignored. This is not exact event-mark funding accounting.
  Independent period 14 days; >=100 closed trades, >=3 symbols, >=95% signal coverage, <=10% drawdown,
  paired daily bootstrap improvement vs controls. ready remains false pending independent execution/cost audit.
- brain_channels.py: stable six-symbol BTC/ETH/SOL/DOGE/XRP/BNB WS collection:
  book50, trades, tickers (OI/funding/mark/index), liquidations and 15m klines.
  Exchange and local receipt times plus monotonic stamps, separate sessions and explicit gap log.
  Five-minute gzip files; 4 GiB/day, 60 GiB total, >=10 GiB free; budget limits STOP collection with gap status, never silently drop.
  Existing recorder remains untouched. News/context service remains available but is NOT a validated predictor.
- brain_microstructure.py: alternate 5s order-flow features, causal snapshot/delta reconstruction,
  signed trades, imbalance, BTC/ETH returns, spread and depth. Delayed 120s long labels use future bid/ask,
  fees and slippage; excludes hour-crossing labels to avoid unknown funding.
  It waits for >=7 days with >=20 sufficiently sampled hours per day, then trains GPU MLP and emits diagnostic results only.
  GPU temperature guard refuses epochs at >=82 C or unavailable telemetry; nonfinite losses fail.
  No automatic promotion. No independent microstructure PAPER implementation yet.
  Per-session warmup and remaining label horizon reduce usable data; coverage/regime diversity need audit.

## Next engineering work — not completed
Restart test: new forward PID restored protocol/capital/positions/trades; new decision counters appended normally.
First prospective forecast recorded. Two REST responses exceeded 1.5 s and were rejected; thresholds were not loosened.

1. Verify newly collected datasets and forecast timeliness, clock offsets, subscription gaps and storage rate.
2. Upgrade microstructure validation: distinct market days/coverage (not merely seven-day span), realistic cross-symbol
   portfolio execution, lot rules, historical funding and fees, no overlapping windows, simple baselines and block CIs.
3. Implement prospective frozen microstructure PAPER deployment only for candidates passing development gate.
   Currently daily micro research is not connected to forward.py (different feature schema); do not claim otherwise.
4. Add restartable optimizer checkpoints for long future training runs, CPU/RAM/GPU thermal resource limits.
5. Verify actual fees via permitted read-only audit, latency/depth replay and funding event marks before readiness.
6. Add genuinely point-in-time news features only after enough first-seen data and ablation evidence.
7. After each rejected approach choose a justified new architecture; do not endlessly refit the same holdout.

## Environment
Use deploy/brain-supervisor.sh environment. PYTHONPATH order matters:
.gpu-torch, .venv/lib/python3.13/site-packages, then existing storage/cuda-packages.
The partial storage sympy install shadows working dependencies if the order is reversed.
Do not replace the working PAPER environment or rerun old install_market_torch.py blindly.
Tests:
env LD_LIBRARY_PATH=/opt/nvidia-driver PYTHONPATH=.gpu-torch:.venv/lib/python3.13/site-packages:/home/codex/projects/market-brain-storage/cuda-packages .venv/bin/python -m unittest discover -s tests

Preserve preexisting unstaged adaptive_live.py, telegram_control.py, web/adaptive.js and legacy untracked training files.
Only new evidence-workflow files and existing motivation dependency are included in the new commit.

## Continuation 2026-10-30: microstructure validation and prospective reservation

The first continuation overlapped the initial evidence-workflow commit.
Commit 9afafc5 already includes the microstructure call sites changed by this
continuation; the follow-up commit supplies their new modules. Preserve both.

Implemented:
- samples-v2 stores session IDs. Labels cannot cross reconnects, missing 5s
  observations, or hourly funding boundaries. Delayed entry and costs retained.
- A stale/out-of-order book delta invalidates book and price history until a new
  snapshot; stale, invalid and future-dated trade events cannot enter order flow.
- Fixed momentum/reversal/cash comparisons, one shared diagnostic wallet per
  strategy, compounded returns, extra 10bp cost stress and paired daily bounds.
- Qualified development candidates reserve ONE immutable future 14-day period,
  beginning next UTC midnight; model, scaler, source and protocol are hashed.
  No candidate currently qualifies, so no microstructure trial has been reserved.
- brain_micro_prospective.py evaluates that fixed future archive once after end,
  using received-time delayed bid/ask labels. Reserved observations are excluded
  from subsequent development. Source/artifact changes invalidate evaluation.
- This is prospective PAPER REPLAY, not the requested full-depth live micro
  PAPER executor. ready remains false even after a statistical pass. Do not
  describe it as complete execution validation. No real-order interface exists.
- Daily supervisor invokes the updated micro workflow without restarting it.
  Original 15m frozen source hashes were verified intact.

Verified operational observations:
- Existing paper/arena/adaptive/Telegram/dashboard services active.
- Mature 5-minute raw session reconstructed: 85,420 messages, 216 feature samples.
- GPU temperature read by NVML: 31 C; no training forced on a few minutes of data.
- 15m trial protocol integrity passed. No wallets reset or service changes.

Remaining: independent LIVE microstructure paper executor with exact lot rules,
depth consumption, mark-to-market drawdown, persistent pending orders and
restart recovery. Current proxy drawdown only observes closed trades. Do not
auto-promote or claim execution readiness. Obtain enough independent market
days before fitting; do not relax gates to manufacture GPU activity.

Validation: full suite 128 tests passed (expected mocked Telegram delivery log).
Code commit: 6d4a689. Push via existing HTTPS origin failed because this device
has no noninteractive GitHub credential helper. Local commits and mounted data
are durable; continue work without resetting or discarding them. Synchronize
using an already authorized credential path when available; never print tokens.


## Continuation 2026-10-31: runtime recovery and impulse data implementation

Goal is ACTIVE, not achieved. No qualified profitable model or independent PAPER
success has been established. Real orders remain prohibited.

Verified and implemented:
- Real CUDA mixed-precision backward + AdamW parameter changes for MLP, TCN,
  GRU, LSTM, Transformer and MoE in two fresh processes, including restoration
  of optimizer/model checkpoints. cuDNN reports 91900 on RTX 5070.
  Evidence: storage/gpu-probe-20261031/probe-*.json. GPU probe is NOT alpha evidence.
- Existing supervisor/children had inherited the OLD LD_LIBRARY_PATH despite
  the launcher correction. Restarted only this isolated evidence workflow.
  New channels/forward processes inherit the corrected cuDNN path. Exact wallet
  dictionaries were unchanged and cycle count advanced. Existing cripto services
  were NOT restarted. Frozen 15m protocol and its source hashes verified intact.
- deploy/brain-supervisor.sh now accepts a Python script/arguments, defaults to
  brain_supervisor.py. Supervisor handles TERM/INT and reaps its own children.
  Existing cron singleton/restart behavior is preserved.
- brain_impulse_data.py: 30 receive-time features (price/volume/volatility
  acceleration, depth/imbalance change, aggressive flow, BTC/ETH leads, OI,
  funding and liquidation position sides). Missing OI/funding have explicit masks.
  Full received top-50 public depth is retained in derived rows. No invented RPI.
- Labels: 10/30/60/120 seconds, long/short, observed depth consumption,
  quantity step and minimum, fee on both actual notionals, slippage, delayed entry.
  No cross-session, missing-sample or hourly funding-crossing labels. Current lot
  snapshots are NOT historical rules; maker queue, funding-crossing execution,
  event-level mark-to-market/liquidation simulation remain unimplemented.
- brain-impulse-data.timer enabled. Bounded 12-file batches every 15 minutes and
  after boot, 70% CPU/768 MiB RAM. Raw files and derived artifacts are preserved,
  source/code hashed, atomic outputs; no wallet/database writes.
- First real batch: 12 archives, 2567 feature rows, 9300 executable label rows.
  Actual sampled latency 5-7 seconds. 8902 labels intersect existing reserved
  prospective periods and are excluded by the new development-mask function.
  Their PnL/scores were NOT inspected. Only 398 unreserved labels: no training.
- brain_impulse_protocol.py: tested reservation-overlap exclusion, per-symbol
  minute/hour/day coverage, contiguous-day requirements, purged expanding folds,
  per-coin/calendar-day PnL, fees, daily bootstrap CIs, leave-best-coin-out PnL.
  These are library helpers, NOT yet connected to a new impulse model trainer.
  The default requires 21 contiguous development days (7 train/7 validation/7
  diagnostic evaluation). Never loosen coverage because data are insufficient.
- Resumed and enabled brain-factory-minute.service. It downloaded 30 days of
  minute history strictly before frozen prospective boundaries, then began the
  bounded 16 architecture/horizon comparisons. Check live summary/progress;
  completion must not be assumed. Completed factory-v1 has 16 rejected trials.

Tests: full suite 140 passed after data/runtime changes; five additional protocol
unit tests passed separately. The expected mocked Telegram-delivery ERROR is a
successful negative-path test, not a live delivery. Factory test also verifies
checkpoint continuation matches uninterrupted GPU optimization exactly.

Paths under /home/codex/projects/market-brain-storage:
- impulse-v1/status.json, quality-audit-20261031.json, <code-sha-prefix>/*
- factory-minute-v2/run/{manifest.json,*/progress.json,*/result.json,summary.json}
- evidence-v1/runtime-restart-before-20261031.json

Next concrete work:
1. Finish/review minute factory results without modifying its frozen source or
   retuning on the same diagnostic block. Persist negative hypotheses.
2. Connect impulse features, reservation exclusions and coverage admission to
   an isolated resumable trainer. Retain checkpoint RNG/optimizer/scaler state.
   Do not feed the reserved 15m trial observations into development.
3. Add causal multi-coin decision-time ranking and full-depth independent live
   PAPER executor; the current label generator is sampled replay, NOT live PAPER.
   Preserve global pause, wallets, pending orders and mark-to-market risk state.
4. News remains excluded until trustworthy first-seen timestamps and ablation.
5. Independent evidence still requires future observation time. No profitability
   claim from synthetic GPU probes, code tests, sparse trades or historical tuning.

API semantics checked against official Bybit pages:
https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook
https://bybit-exchange.github.io/docs/v5/websocket/public/ticker
https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation
