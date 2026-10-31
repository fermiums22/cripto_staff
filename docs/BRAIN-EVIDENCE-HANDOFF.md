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

Minute factory subsequently COMPLETED successfully: all 16/16 rejected. Best
positive model was GRU/4m +$0.12370 on ONE trade; ridge/1m +$0.09690 on TWO.
Neither establishes advantage. MLP/1m -$0.46336 (13 trades), stressed -$0.59820
from $15; LSTM/4m -$0.35350 (11 trades). See docs/brain-minute-results-2026-10-31.json.
Do not repeat this family on the same evaluation period. Source/model/checkpoint
artifacts and summary are preserved. The enabled service exits on its existing
summary after reboot rather than retraining it.

Branch research/impulse-20261031 published via workstation Git Credential Manager;
container HTTPS push has no credentials. Workstation transport-only bare repo:
D:/HAOS/server-control/brain-development-20261031/sync.git. Bundle transport avoids
copying any credential onto the server. Existing uncommitted adaptive_live.py,
telegram_control.py, web/adaptive.js and legacy files remain untouched.


## Continuation: durable impulse execution and historical depth access (2026-10-31)

The preceding goal turn made progress (code, GPU evidence and rejected minute
experiments). This turn also made concrete progress. Goal remains ACTIVE: there
is NO demonstrated profitable candidate and NO successful independent alpha trial.
The owner's household financial needs do not relax the PAPER-only restriction or
statistical/risk gates. Do not promise income or treat deployment as profitability.

Implemented:
- brain_impulse_execution.py: shared deterministic PAPER engine, causal ranking
  of net-return estimates, one position, delayed entry AND exit, observed full
  visible depth consumption, quantity/minimum/maximum rules, actual entry/exit
  notionals for fees, mark-to-market exit costs/drawdown, fixed risk limits and
  reduced notional after losses. Pauses cancel entries but continue exits.
- DurablePaper: SQLite FULL-synchronous transactions store deduplication keys,
  complete input payloads including instrument rules, account, intent/event and
  trade journals atomically. Protocol or policy mismatch refuses wallet reuse;
  there is no reset API. Completed trades are outside the compact account state.
- brain_impulse_audit.py: consistent database backup followed by independent
  event replay, exact account/trade comparison and cash/fee accounting identity.
  It distinguishes operational_pass from financial_qualified (always false).
- brain_impulse_live.py + brain_impulse_controls.py: public WS books/trades/
  tickers/liquidations, periodic public instrument snapshots, causal 500ms gather
  window for cross-symbol ranking, per-position books sampled at >=200ms,
  read-only global pause (errors fail closed), bounded reconnect/warmup behavior.
  Control forecasts are FIXED UNTRAINED momentum/leadlag-flow heuristics, NOT
  established expected returns. No model loader/promotion or real-order client.
  Candidate remains CASH. Source snapshots/hashes and policy are immutable.
- brain-impulse-paper.service enabled and running at 70% CPU / 768 MiB maximum.
  Only its own directory is writable; secrets are inaccessible. Existing cripto,
  Telegram and household units were not restarted or changed.

Live validation:
- Finite 180-second audit consumed 27,476 real public messages, terminated cleanly,
  made six decisions per control and NO trades (no qualifying estimated edge).
  All three durable journals replayed exactly with zero accounting residual.
  This proves transport/decision/ledger integrity, NOT real fill profitability.
- All 158 tests passed, including delayed full-depth fills and fees, open drawdown,
  no risk escalation, pause semantics, same-quote rejection, reconnects, event
  identity/tamper detection, policy protection and checkpoint restoration.
- Initial live audit exposed silent loss of features after book invalidation.
  Added a continuity watchdog: invalid leader book or 20s feature outage forces
  a new snapshot/warmup rather than staying falsely healthy. No gate was loosened.
- Ongoing service restart verified PID 2657 -> 2699 with EXACT account state
  preservation while flat. Existing six PAPER/dashboard/Telegram units active.

Paths:
- storage/impulse-paper-audit-20261031: immutable finite audit + source + journals.
- storage/impulse-paper-control-v1: ongoing control wallets, source/protocol,
  status.json, connection-error.json, instrument snapshots, restart-audit.json.
  Do not modify the four frozen source files while this trial is in progress
  without preserving/invalidation/migration of the trial. Stop/promote nothing
  merely because a control becomes briefly profitable.

Execution limitations remain explicit:
- Taker .0006 and slippage .0003 are conservative SCENARIOS, not verified personal
  fees. Maker queue and partial IOC fills are not implemented.
- Entries avoid hourly funding boundaries. Unexpected crossings (e.g. outage)
  add unresolved_funding, halt entries and invalidate evidence; funding settlement
  and the numeric provisional cash are not an exact funded PnL in that case.
- 1x insolvency protection is NOT Bybit maintenance-tier liquidation modeling.
- This is a live CONTROL/execution audit; trained impulse models are not wired in.
  Research/selection/live-candidate promotion still needs implementation.

Important new data route (do not wait weeks merely to obtain development depth):
Official Bybit archive pages and direct download hosts were verified. The new
brain_archive_probe.py downloaded and fingerprinted a closed SOL day, bounded
storage, resumable HTTP Range partials, no credentials:
  https://public.bybit.com/trading/SOLUSDT/SOLUSDT2026-10-01.csv.gz
  https://quote-saver.bycsi.com/orderbook/linear/SOLUSDT/2026-10-01_SOLUSDT_ob200.data.zip
Archive probe: storage/archive-probe-20261001/probe.json. Trades 16,937,934 bytes;
200-level book 60,352,468 bytes. ZIP contains a .data JSONL stream with standard
Bybit snapshot/delta, ts, cts, b/a/u/seq. Trades CSV includes timestamp/side/size/
price/RPI. Only initial record schemas/timestamps and compressed download hashes
were checked; full reconstruction/coverage/CRC need validation before training.
These archives have exchange timestamps, NOT local historical receive times.
Do NOT label archive replay as independently measured live latency. Apply explicit
latency scenarios, exclude RPI trades when unavailable to the book, preserve gaps
and sort/merge by source time without future information. Same calendar history
previously inspected at 1m/15m remains development, not pristine final evidence.
Sources: https://www.bybit.com/en/derivative-activity/history-data and
https://bybit-exchange.github.io/docs/v5/market/recent-trade .

Next high-value work:
1. Validate/stream-merge historical books and trades for BTC/ETH + four alts on
   fixed development dates; budget downloads before expanding. OI/funding masks
   stay unknown unless genuine timestamped observations exist. No invented data.
2. Connect that data and live-derived samples to the bounded resumable GPU model
   competition, purged folds and execution engine. Preserve all reservations.
3. Run model selection once per fixed hypothesis protocol, then frozen independent
   future PAPER with cost/depth/coverage/coin-diversification confidence gates.
4. Finish maker/partial/funding/margin accounting before claiming execution-ready.


## Continuation 2026-10-31: historical stream campaign and GPU impulse models

Goal remains ACTIVE; no demonstrated net edge or independent successful candidate.
The prior conversational response made no research progress. This continuation
revalidated the live jobs and completed the implementation checks below.

- Added bounded resumable six-symbol archive downloads, stream merging with
  explicit simulated receipt delays, full ZIP/gzip consumption and checksums.
  Adjacent midnight spill records are clipped and counted, not treated as a new
  day's history; larger wrong-day records fail. RPI trades are excluded.
- Pilot reconstructed 9,018,727 messages into 99,659 feature observations.
  Failed pre-fix output remains preserved separately. Successful derived path:
  storage/archive-pilot-v1/derived-d6cb8fcd167d.
- brain_impulse_dataset.py writes immutable, hashed binary arrays: eight trailing
  observations of 30 features, eight long/short 10/30/60/120-second net targets.
  Reservation, session, gap and hourly boundaries are excluded. Targets remain
  sampled-depth FIXED-HORIZON proxies, not full risk-stopped portfolio PnL.
- Fixed Oct 1-21 campaign preflight checked 252 files, 14,798,627,880 bytes total;
  32 GiB raw budget, 512 MiB/file, 10 GiB free reserve. Source code, source ETags,
  instrument scenario and reservations are frozen in campaign-plan.json.
  brain-archive-campaign.service enabled: CPU quota 100%, RAM 1280 MiB, no swap,
  own storage paths only, restart-on-failure with bounded retry rate.
  Last live check: PID 3313, active, NRestarts=0, RSS 70,404 KiB. Three completed
  days passed coverage, all four alts have 24 qualified hours/day. Target counts
  61,848 / 53,531 / 58,709. The remaining days are not yet verified complete.
  MemoryCurrent near cgroup cap includes filesystem cache; process RSS is small.
- Added brain_impulse_models.py: MLP/TCN/GRU/MoE eight-output net-return regressors,
  train-only scaling, lookback-aware temporal purge, bounded AMP optimization,
  thermal guard, early stopping, model/optimizer/scaler/RNG checkpoints and
  immutable experiment/data/index identities. No orders or auto-promotion.
- GPU tests actually ran all four backward passes with finite parameter gradients.
  MLP checkpoint resume matched uninterrupted training bit-for-bit. Full suite:
  170 tests PASS (expected mocked Telegram error and matplotlib warning).
  Real Oct 1 dataset loader verified hashes, 61,848 targets, shapes (2,8,30)/(2,8),
  finite sampled arrays and causal time bounds. No prediction/PnL selection made.
- Existing live impulse controls still candidate CASH, zero closed trades at
  last inspection. Campaign and control source freezes preserved. Existing
  unrelated dirty adaptive/Telegram/frontend changes were not staged.

Next required work: build the immutable competition orchestrator with simple
controls and boosted trees, purged walk-forward folds, validation-only selection,
shared risk-stopped execution replay, daily/coin/concentration uncertainty and
cost/latency stress. Connect trained candidates to a distinct frozen future PAPER
trial only after gates pass. Neural helper tests are NOT a model competition or
profit evidence. Historical receipt delays/current lot rules remain scenarios;
news/OI/funding/liquidations are not invented where archives lack them.
Do not modify campaign CODE files while it is running. New orchestration modules
can be developed independently. Data location: storage/archive-campaign-v1.
