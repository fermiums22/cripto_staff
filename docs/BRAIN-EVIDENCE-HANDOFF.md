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


## Continuation: event-depth control replay (2026-10-31)

Previous turn made concrete progress (32246c9, published). This turn adds
brain_impulse_replay.py without modifying any frozen campaign/live-control code.
archive_events validates raw hashes, reconstructs actual book deltas, feeds
200ms-limited depth quotes plus causal feature observations and raw-message clock
advances. The replay uses the SAME execution engine as live controls: 500ms
signal gather, delayed taker fills, actual visible depth, fees, stop/drawdown and
funding/gap invalidation. It does not replace execution with fixed-horizon labels.
Each forecast must match its causal observation timestamp/symbol/session.
New entries stop 180 seconds before evaluation end; no later prices are used.
Unclosed positions at EOF are flagged unresolved, never fictitiously liquidated.
Closed-trade PnL and final marked equity are separate; accounting is reconciled.
Per-day bootstrap/coin/fees reports use the existing diagnostic reporting helper.
This is historical scenario evidence, NOT independent PAPER or historical measured
latency. 200ms sampling may still miss intrainterval moves; maker/funding/tier
limitations of the shared execution engine remain.

Verification: 174 tests passed. Four new tests demonstrate causal gathers/fills,
stop execution between feature samples, EOF invalidation and future/clock guards.
A full Oct 1 control audit is RUNNING as brain-impulse-replay-audit.service,
verified PID 3566 active. Output: storage/impulse-replay-audit-v1/result.json;
identity.json freezes sources/raw plan/instrument snapshot and interval. Initial
launcher attempt failed importing repo modules; fixed only the standalone runner's
sys.path and restarted after confirming the failed process. No wallet reset.
This is a transient systemd unit, NOT reboot-enabled; rerun saved run.py with the
project launcher if interrupted (it preserves completed result and identity).
Do not change replay source until this audit completes. Inspect the actual unit
and result before drawing conclusions. No financial result is claimed yet.
Campaign PID 3313 still active, four completed days, processing Oct 5.

Next: integrate bounded model/baseline competition and train-only window inference
with this evaluator. Need immutable folds, validation selection and final untouched
prospective trial; historical control audit alone cannot meet the user goal.


## Continuation: causal neural inference bridge (2026-10-31)

Previous turn made progress (c6bf569, published); goal still unachieved.
Added brain_impulse_inference.py, independent of frozen active trial sources.
SequenceSignals constructs eight past observations per symbol, clears on >7s
sampling gaps/session changes/reservation exclusion, rejects duplicate/regressing
clocks, and emits all eight net-return outputs with explicit horizon/side mapping.
Invalid feature/output/scaler/uncertainty values fail closed. Neural adapter uses
identical training scaling/clipping and converts percentage units back to returns.
It is a callable compatible with replay's predictor interface, not an automatic
model loader/promotion or a trained candidate. New instances are required per
trial. Predictor weights/scaler/artifact identity still must be frozen by the
forthcoming competition orchestrator.

Evidence: all 178 tests PASS; actual Oct 1 archive streaming produced EXACT input
window matches for 256 target examples from the binary training dataset. Saved
storage/impulse-replay-audit-v1/inference-parity.json (engineering, not alpha).
Campaign PID 3313 remains active: five completed days, downloading Oct 6 at last
check. Control replay PID 3566 remains active, elapsed 3:13, CPU time 2:07, RSS
50,632 KiB; result not yet written. This is a verified running job, not a timeout
failure: do not restart it. Six existing cripto services verified running.
No candidate trained/promoted this turn, no edge claim. Next substantial step is
the immutable experiment orchestrator: admitted campaign, purged folds, boosted
baseline, bounded neural fits, validation-only selection and event-depth replay.


## Continuation: calendar folds and bounded neural training stage (2026-10-31)

Previous turn made progress (4a7bff0, published). No profitable edge is established.
Added brain_impulse_splits.py: admission requires 21 ordered contiguous days,
all four alts >=20 qualified hours/day, matching campaign/dataset manifest hashes.
It freezes first 14 days as development and final 7 as diagnostic. Two expanding
folds use day offsets (train end, early-stop end, score end): (7,9,11), (9,11,14).
180s purge applies to both actual feature-history start and label end. Index order
is explicitly chronological even though targets were written by completion time.
The new helper avoids the legacy walk_forward issue where end[-1] slightly before
midnight could reject a fully covered exact-21-day campaign. Legacy helper remains
unchanged; use the new manifest/calendar path for this competition.

Added brain_impulse_train.py CLI --campaign PATH --output PATH: exactly eight
neural fits (4 architectures x 2 folds), 25 maximum epochs each, early stopping,
optimizer/RNG resume from existing model helper, immutable source/split identities,
validation predictions and hash-verified per-model completed artifacts. It loads
ONLY the first 14 days; final diagnostic arrays are never loaded. Status/summary
explicitly say training stage only, no promotion. Do not treat neural validation
predictions as completed baseline/execution comparison. GPU fitting has NOT been
launched: campaign is not yet fully admitted. No fake training on partial history.

Checks: 181-test full suite passed; subsequent orchestrator isolation/resume/tamper
unit test passed separately (182 tests total now). Test verifies only development
paths reach Frames, all eight fits finish, second invocation skips them, and altered
model artifact fails. Fixed the test-exposed lock-file resource leak with a context
manager; focused test passed again. Neural numerical/backward tests remain those
already verified on CUDA, not this mocked orchestration test.

Latest live check: campaign PID 3313, six completed days, processing Oct 7; control
replay PID 3566 active and result pending. Do not restart either based on waiting.
Next: boosted-tree/ridge baseline training, validation event-depth comparison,
uncertainty/stress/selection protocol, then controlled access to diagnostics.
No model live deployment or independent success has occurred.


## Continuation: ridge/XGBoost competition and completed control audit (2026-10-31)

Previous turn progressed (4cac1a0). Goal remains ACTIVE, no qualifying edge.
Added brain_impulse_baselines.py: ridge and XGBoost independent regressors using
90 last/mean/change features from the same eight causal observations. Only train
indices accepted; max 100,000 evenly spaced chronological examples bounds memory.
Ridge fixed L2=10 and train-only scaling. XGBoost installed version 3.1.1: CUDA hist,
depth3, bins64, eta.04, lambda10, child20, 96 fixed rounds, no hyperparameter search.
Checkpoint each four rounds with atomic progress pointer/checksum; resumed fits
preserve the same chunk schedule. Actual booster config must report cuda:0; no
silent CPU fallback. Predictors emit eight net returns compatible with SequenceSignals.
brain_impulse_train now runs SIX approaches x TWO folds = 12 bounded fits, hashes
baseline artifacts and validates finite prediction shapes. No diagnostic loading.
No market training launched before full 21-day admission; rules remain separate
untrained execution controls. Future selection still needs event-depth validation.

Verification: 184-test full suite PASS. Actual CUDA boosted multi-output training
and interrupted/resumed equality passed. Ridge ignores poisoned nontrain rows;
changed experiment identity or damaged completed artifact fails. XGBoost emits
'nvidia-smi: not found' in this container, but actual booster device config and GPU
training tests succeed; no driver/env changes were made. API references consulted:
https://xgboost.readthedocs.io/en/stable/tutorials/multioutput.html
https://xgboost.readthedocs.io/en/stable/gpu/index.html
Installed API/version were inspected locally rather than assuming latest requirements.

Control audit COMPLETED (brain-impulse-replay-audit MainPID=0, exit0, inactive).
Full result storage/impulse-replay-audit-v1/result.json; identity preserved.
9,018,716 in-interval events, 2,188,876 depth quotes, 99,659 samples; raw input CRC
exhausted. Momentum: 10 trades, net -$0.2908396399643891 (-1.93893%), fees $0.1421731,
MTM drawdown 1.93927%, ending $14.70916036. DOGE 5 trades -$0.11056133; SOL 1 trade
-$0.04514280; XRP 4 trades -$0.13513551. Cash and leadlag_flow had zero trades.
No execution evidence issues, accounting residual <1e-15. This is NEGATIVE one-day
historical scenario evidence. Its one-day bootstrap CI is degenerate and MUST NOT
be interpreted as statistically meaningful; no independent trial or alpha pass.
Campaign remains active, seven completed days, processing Oct 8 at last check.

Next: finish admitted dataset, run fixed 12 fits, execute validation folds with
frozen models/controls and cost/latency stress, choose or reject before diagnostics.
Need multi-day paired uncertainty, concentration and execution gates before any
independent candidate PAPER trial. Preserve all frozen active source files.


## Continuation: validation rejection policy frozen before fitting (2026-10-31)

Previous turn progressed (3ad615b). Goal remains ACTIVE; no new alpha evidence.
Added brain_impulse_selection.py, consuming actual event-depth replay ledgers, not
regression MSE. Requires full fixed six-model family plus CASH/momentum/leadlag_flow
controls, both base and stress, identical calendar days; reconciles per-trade,
per-day, net PnL and fee totals. Rejects execution issues, nonpositive folds/stress,
>10% MTM drawdown, <100 trades, <3 symbols, nonpositive PnL removing best coin,
>60% positive coin PnL share or >20% positive trade PnL share. Paired two-day
circular-block bootstrap includes idle days, minimum five days, fixed seed 7301,
20,000 resamples, one-sided family adjustment across 6x3 model/control comparisons.
Small five-day development samples are not independent proof; this gate allows
ONLY later diagnostic evaluation, never live promotion. Final readiness always
false; no winner becomes PAPER-ready merely by passing this helper.

Policy and source hash frozen now in storage/impulse-competition-v1/selection-policy.json:
SHA256 052f9e4eca23d7f1b8b13456ea3e31f4dc289f904e082a3309ad667ebd468b11.
Training runner now checks that freeze and includes its digest/source in identity.
Use impulse-competition-v1 as the output directory for upcoming training. Do not
silently edit selection source or gates after seeing candidate outcomes. No market
fits started yet. Full validation execution orchestration/stress policy binding and
winner diagnostic activation remain unimplemented; do not call the selector on
proxy labels or promote automatically.

All 189 tests pass, including rejection of concentrated profits, negative stress,
missing/misaligned controls, forged fee ledger, too few days, and lack of paired
advantage. Synthetic positive fixture only receives diagnostic eligibility;
live_promotion_allowed remains false. Campaign PID 3313 active, NRestarts=0,
eight completed days, downloading Oct 9. Existing live source/wallets untouched.
Next: implement validation model loading/artifact checks and actual frozen
multi-day execution/stress orchestration; complete admitted 21-day data and fits.


## Continuation: frozen execution validation and automatic workflow (2026-10-31)

Previous turn progressed (f5c2725). Goal remains ACTIVE; no positive edge proven.
Added brain_impulse_evaluate.py: checks training/source/split/selection identities,
all 12 model result records against summary, every model artifact hash, raw plan
campaign identity and frozen instrument scenario. Loads CPU inference weights and
scalers for four neural plus ridge/XGBoost, wraps causal SequenceSignals and adds
three fixed controls. Replays calendar score intervals days 9-11 and 11-14 only;
rejects attempts to access diagnostic days 14-21. Base policy unchanged; stress
fee .0008/side, slip .0008/side, 2000ms execution delay. These are SCENARIOS, not
verified personal fees. Archive receipt delays stay explicit simulations.
Each full fold/scenario result is atomic with payload checksum and plan hash;
completed runs are resumed without replay, while artifact checks still run.
Shared selector writes validation-selection.json, diagnostic eligibility only.
No final diagnostic or independent model PAPER deployment is implemented yet.

Optimized replay quote routing to match live: only pending/position accounts see
book updates; flat accounts avoid millions of unnecessary mutations. Original
completed negative control audit and its identity remain preserved; source version
for that audit is in Git before this change. No active trial sources were changed.

Checks: full suite 192 passed before final loader/checksum additions; final focused
4-test evaluator suite passed, bringing test inventory to 193. Actual saved random
MLP/TCN/GRU/MoE weights/scalers loaded and emitted eight predictions; damaged model
file rejected. This is engineering verification, not trained-market performance.
Mock orchestration validates four fold/scenario passes, replay reuse and protected
final dates. Real neural/baseline GPU checks remain previous verified tests.

Execution policy/source freeze created BEFORE market fitting at
storage/impulse-competition-v1/execution-policy.json, SHA256
1e3a41a102a96276e05bf90c9f3688f99b40b979eb6da204b375ec414d644d90.
Do not modify its CODE sources silently; preserve/invalidate/version trials for
necessary corrections. Selection freeze remains unchanged.

Added brain_impulse_workflow.py and enabled brain-impulse-competition.timer.
Every 15 minutes after the previous run, and after boot, isolated oneshot checks
complete admitted campaign then invokes training and validation sequentially.
CPU quota200%, memory4GiB, swap0, nice15, private tmp, read-only filesystem except
its own output, secrets inaccessible. No real-order/promotion code exists.
Source units verified; first real service run exited0 with
workflow-status.json stage waiting_for_complete_campaign. This is correct, not a
training result. Timer is enabled and will start bounded work when all21days pass.
Interruption resumes completed model checkpoints/fold-scenarios; an unfinished
replay scenario restarts from its beginning, not an invented midstream account.
Unrelated systemd verify warning references existing codex-home-ca-http service;
that service was not modified. Household/old PAPER wallets remain untouched.


## Continuation: selected-model diagnostic and measured live bottleneck (2026-10-31)

Previous turn progressed (f89ea64). Goal ACTIVE, no qualified positive expectation.
Added brain_impulse_diagnostic.py: recomputes verified validation selection from
cached event-depth results; CASH leaves final historical sources unopened. Only
selected fold1 weights + three controls are replayed on days14-21, base and stress.
No retraining, threshold tuning, alternative-model inspection or live promotion.
Checks raw campaign/model/selection/policy identity, atomic checksum-protected
scenario results, seven-day accounting/paired controls/risk/concentration gates.
Pass means eligible_for_new_future_paper only; historical period was previously
inspected at candle resolution and is NOT independent new evidence. All readiness
and live-promotion flags remain false. Workflow now invokes diagnostic stage after
validation; if rejected it finishes with no candidate and no final-data inspection.

Full suite 195 tests passed. Diagnostic tests demonstrate only prospective PAPER
eligibility from synthetic success and no access to final paths when CASH selected.
Frozen before fitting: storage/impulse-competition-v1/diagnostic-policy.json SHA256
86ccf8142a351caae5149fcd1b9e9af838fa80ea09eb018a623062fdfee6391f.
Frozen prior selection/execution source files were not modified. Workflow is an
operational wrapper; its added diagnostic invocation does not alter those trials.
Campaign verified running, 12 completed days at last check, processing Oct13.
GPU idle31C, 0% utilization,0MiB at that sample. No overheating observation.

Important actual live finding; prioritize before candidate PAPER:
- Existing impulse control service active PID2699, but frequent leader-book
  invalidations/reconnects (35+). Its CPU only1.7%, ~49MiB RSS, so CPU saturation
  was not observed. No wallets reset, no freshness thresholds loosened.
- Separate public-stream 120.2s probe completed exit0: 13,655 book messages,
  2,951 tickers,342 trade messages,69 feature samples. Book latency p50=94ms,
  p99=99ms,max712ms. Only six initial snapshot resets, no erroneous book sequence
  or timestamp invalidation in this window. Some stale tickers reached2010ms.
  Source/result: storage/impulse-transport-audit-v1/probe.py and result.json.
  First20s attempt failed from probe-only ping serialization typo; failed source
  and partial result preserved separately, corrected attempt ran120s. Active
  frozen live service was never edited/restarted by this audit.
- Separate synthetic durable SQLite benchmark on SAME mounted storage, new isolated
  accounts, 50 cycles/150 FULL commits: 3-account decision cycle p50=290ms,
  p95=3856ms,p99=4445ms,max4545ms. Single commit p50=86ms,p95=1351ms,
  p99=2215ms,max2688ms. storage/impulse-ledger-latency-audit-v1/result.json.
  This is sufficient to make same-thread socket reads exceed1500ms freshness.
  It is a measured bottleneck and plausible reconnect cause, NOT proof that every
  existing reconnect came from storage. The read-only probe did not reproduce it.
- Next required live engineering: separate timestamped socket ingestion from slow
  durable writes using bounded buffering/backpressure and fresh decision-clock
  checks, preserve fail-closed behavior, and version the trial (do not silently
  patch frozen live/data sources). Never merely accept stale prices or move/reset
  existing wallets. Validate with controlled slow storage plus real public stream.


## Continuation: bounded asynchronous receipt with actual slow-ledger audit (2026-10-31)

Previous turn progressed (6bfd214). No profitable candidate or independent PAPER
success; objective remains active. Current campaign continues, thirteen completed
days at last check, extracting Oct14; no source gates loosened.

Added brain_impulse_transport.py: independent socket thread timestamps messages
IMMEDIATELY at recv completion with wall and monotonic clocks, preserves source
order and session/sequence, pings in receiver thread, uses bounded 10,000-message/
8MiB queue. Overflow, oversized payload, clock regression or subscription failure
invalidates connection; no delta is silently dropped. Consumer may reconstruct
historical rows but fresh_for_decision checks both processing delay and exchange
age against1500ms, including after each slow account write. Thread closes cleanly.
This is an ingestion component, NOT yet integrated into frozen live control/model
runner. Do not claim live service bottleneck fully fixed or alter frozen sources.

Added brain_impulse_transport_audit.py, finite public WS + three isolated synthetic
CASH journals on the same persistent storage, actual FULL commits, deliberate
4.5s consumer-only stall. No orders, no existing wallet edits, no model inference.
Audit completed exit0, duration120.79s; storage/impulse-buffered-audit-v1 contains
source identity, all three journals and result.json. Results:
- 17,713 received messages,17,626 processed before finite stop;87 queued at close
  explicitly reported, NOT claimed fully processed. Peak650 messages/182,668B,
  no transport fault/overflow.
- Book receipt lag p50=95ms,p99=101.59ms,max639ms despite consumer stall.
- Queue age max4499.67ms,p99=3176.01ms: delay is recorded, never relabeled fresh.
- 71 feature samples,8 stale samples rejected. Only six initial book snapshot
  resets, no book continuity loss observed in this finite window.
- 24 synthetic CASH decisions: accounts9/8/7, because freshness was rechecked
  after preceding slow writes. All cash15, no positions/pending entries.
- Ledger batch p50=542.71ms,max2134.17ms. Buffered receipt stayed timely even while
  processing was blocked. This demonstrates separation, not alpha or real fills.

All198 tests pass, including actual CUDA tests from existing suite and three new
transport tests: receiver drains without consumer, strict ordering/timestamps,
overflow invalidation rather than skipped deltas, oversized/clock-regression
failure and refusal to trade stale buffered observations.
Next: integrate receiver into a NEW versioned live candidate/control runner with
separate receipt and actual processing/decision clocks, per-account fresh checks,
backlog/gap accounting and durable recovery. Never replay queued old quotes as
fills at a fabricated current timestamp. Preserve raw receipt times; use explicit
execution-observed timestamps where processing differs and audit this separately.
Frozen prior trials/source/old wallets remain intact. Current trained candidate
selection and diagnostic still await completed21-day archive and bounded fits.


## Continuation: buffered live control execution audited (2026-10-31)

Previous turn progressed (deee375). Goal remains ACTIVE; no profitable strategy.
Added brain_impulse_buffered_live.py as a NEW finite control runner, leaving old
frozen live service/source/wallets untouched. It combines BufferedReceiver, causal
ImpulseSampler and DurablePaper. Feature times are original receipts; decisions
and executions use actual processing wall time, retaining source_received_ms,
source event time, receive_sequence and processing_delay_ms in book journals.
Both wall and monotonic freshness are checked per-account after earlier writes.
Received quotes preceding pending.eligible_ms are rejected even if processed later:
no retroactive fill at a pre-latency quote. Source/protocol snapshots are immutable.
Global pause, fixed risk, pending positions, journal replay and finite closure
remain enforced. No model loader/promotion or real-order interface was added.

Tests: all201 passed. New tests verify separate receipt/processing clock fields,
stale rejection, pre-latency quote exclusion and actual delayed entry, and invalid
book refusal. Existing CUDA/resume/accounting tests remain passing.

Actual 180s audit completed exit0, no reconnects/failures; directory
storage/impulse-buffered-live-audit-v1, protocol SHA256
86495f48ba7e61a57fada195dcceeeae997ec78f52845fdac93d748da816afc1.
43,720 received,43,675 processed,45 queued explicitly reported at finite shutdown;
137 feature samples,16 decisions per control, no trades. All3 accounts15, flat,
halted by finite-audit termination, no unresolved positions. Independent consistent
SQLite replay passed exactly for all3:17 events each, zero accounting residual,
zero evidence issues. ledger-audit.json saved. This proves transport/ledger logic,
NOT successful independent trading or positive expectation. No new ongoing live
service installed; the finite audit is stopped. Do not reset its closed journals.

Remaining performance limitation:4,067/43,675 processed messages (~9.31%) failed
freshness at processing; intermediate sample reached~14%. Peak queue2286 messages
(641,469 bytes), no overflow. Buffer preserved sequence, but it does NOT make slow
storage fast or guarantee decision coverage. Some stale ticker source times may
also contribute; stale-row ratio is not a direct estimate of missed opportunities.
Investigate bounded batched durable commits/asynchronous journal architecture with
correct intent/decision ordering before claiming readiness. Do NOT disable FULL
sync, accept stale data, or move existing wallets casually to hide this issue.
Read-only storage check: research output on NFS4,159GiB free; container root only
1.4GiB free (96% used). A local spool would require explicit bounded capacity and
restart/durability design; no mounts/NAS/root filesystem changes were performed.
Campaign last verified15 completed days, extracting Oct16; training awaits21.
Frozen training/selection/execution/diagnostic sources remain intact.


## Continuation: atomic grouped journals with measured latency comparison (2026-10-31)

Previous turn progressed (f8619d7). Goal ACTIVE; no demonstrated positive edge.
Added brain_impulse_ledger.py BatchPaper: one DELETE-journal/FULL-synchronous SQLite
transaction for a named group of accounts/events, atomic state/trade/event/batch
identity persistence. Exact prior account/protocol/policy set required on reopen;
rejects legacy wallet schema and implicit migration/reset. Invalid later account
rolls back the entire group, duplicate batch keys idempotent, changed payload fails.
Normal restart restores exact accounts. Initial schema interrupted during first
creation fails closed if partial; no automatic reset/reinitialization of partial
existing DB. A future constructor hardening can make initial DDL transactional.
Added brain_impulse_group_audit.py: consistent backup, replay all batch inputs,
exact state/trade comparison per account and independent accounting identity.

Added separate finite brain_impulse_group_live.py, preserving buffered receipt and
actual processing clocks/freshness gates. All controls' decisions/books/halts are
committed as one group. No old DB migration, no existing wallet reset, no change
to prior frozen control sources, no model promotion. Source snapshots preserved.
All205 tests pass: batch rollback, exact single-account equivalence through a real
synthetic entry/exit and reopen, journal replay, tamper detection, protocol rejection.

Interleaved 40-cycle benchmark on same NFS, alternating batch/singles order, exact
final account-state equality; storage/impulse-batch-benchmark-v1/run.py/result.json:
- three separate commits p50=353.72ms,p95=4290.66ms,p99=10532.72ms,max13734.50ms;
- one grouped commit p50=102.30ms,p95=1190.17ms,p99=2384.91ms,max3086.83ms.
This is an engineering performance sample, not a guaranteed future latency bound.
FULL synchronization unchanged. Disk tails still exceed1500ms; freshness checks
are mandatory. Raw timing pairs are retained, not just selected statistics.

Actual180s group live audit completed exit0, zero failures/reconnects; directory
storage/impulse-group-live-audit-v1, protocol SHA256
c450a2f8e4fcb3c45c238ca04f99516501f4f8b4f0312fce29120c87bbc178eb.
34,496 received /34,394 processed /102 queued at finite close,138 feature samples,
18 decisions per control;19 committed groups including finite halt. All accounts
cash15, no trades or unresolved positions. Group audit reproduced exactly, zero
accounting residual/evidence issues. Candidate CASH, ready false.
2,692/34,394 (~7.83%) stale processed rows; peak1499 buffered messages/332,698bytes.
Do not present this separate market window versus the previous9.31% window as a
controlled strategy performance comparison. Tail latency remains unresolved;
these are operational/control audits, not independent successful trading.

Campaign last verified18 complete days, extracting Oct19. Automatic competition
continues waiting for all21 admitted days. No changes to frozen research pipeline
or household/PAPER services. Next priority: inspect actual bounded GPU training
once admission is complete; evaluate all rejections honestly. For future candidate
PAPER, preserve grouped durable intents and quantify usable-decision coverage,
not just raw messages or lack of reconnects.


## Continuation: full data admitted, real fitting started, AMP correction resumed (2026-10-31)

Previous turn progressed (9d8e43a). Goal remains ACTIVE; no proven positive edge.
Campaign COMPLETED exit0: all21days admitted,1,255,616 targets, all four altcoins
24 qualified hours/day. Raw/hash/source/reservation artifacts retained. No final
P&L was inspected. Strict source freezes verified before fitting.
Production-service-constrained CUDA preflight passed5tests: four-network backward,
MLP exact optimizer/RNG resume, XGBoost CUDA/resume and ridge/scaling guards, peak
1.6GiB under4GiB limit. Evidence v1/service-preflight.json. This preflight alone
was NOT sufficient to prove long AMP training stability (see actual failure).

Operational fix: service StartLimitIntervalSec3600/Burst3 inadvertently counted
successful15-minute waiting runs and blocked training. Changed interval to900s,
retained burst3/resource/security limits, reset only this unit's failed status.
Actual v1 then trained ridge/XGBoost and MLP epochs0-5, failed during epoch6 with
Nonfinite impulse gradient. GPU34C and peak2GiB: not thermal/OOM. Timer was stopped
only while repairing this isolated research workflow, not household/PAPER units.

Corrected brain_impulse_models.optimizer_step: finite-loss FP16 gradient overflow
reduces GradScaler scale and retries SAME batch, at most8 reductions. No invalid
optimizer update, no skipped training example, no accepted nonfinite loss/FP32
norm. AMP scale/retry counts included in progress. Full suite206 tests PASS;
forced-overflow CUDA test confirms scale reduction and exactly ONE optimizer step;
previous exact checkpoint-resume test still passes.

Failed v1 is preserved verbatim, including runtime-failure.json and copies of its
frozen training/execution sources under runtime-failed-source. No old frozen hash
was overwritten to pretend the new code was used in the old run.
Added brain_impulse_precision_resume.py: explicit COPY-only lineage to NEW
storage/impulse-competition-v2. It requires unchanged splits/selection and only
brain_impulse_models.py training-source change; preserves ready ridge/XGBoost
artifacts and MLP checkpoint epoch5. Only experiment/source identity metadata is
updated in the new copy; every model/optimizer/RNG/AMP/best-weight tensor/value was
compared exactly after serialization. New source/policy/plan hashes frozen in v2.
Old plan f2fa468a208ca2c91dcaded5b81c87dac0287c999be437402a9afc9c8d5275bf;
new plan d986dbc350e2bffa7d87a5553f1dd8960f70b64b4387aaa37955f0a4d7a06682.
Full lineage: v2/precision-resume-lineage.json. This is a documented runtime fix,
not outcome-driven retuning or a new hypothesis search. Neither baseline refitted.

Service output/writable path now v2. Timer re-enabled/running; actual workflow
MainPID5443, ActiveState activating (normal long oneshot), memory~1.98GB. At last
check3/12 fits completed, training fold0 TCN. Resumed MLP passed failing epoch,
finished early-stop at epoch15/stall5, GPU35C. Its MSE is NOT financial evidence.
The workflow will proceed to event-depth base/stress validation and ONLY selected
candidate's diagnostic block. No real orders or autonomous live promotion.

Next: inspect actual GPU fit outcomes/execution validation, preserve failures and
rejections. Do not modify v2 frozen sources while running. Before future trained
live wiring, audit archive-vs-live feature contract: archive OI/funding/liquidation
channels are missing and receipt delay is simulated/near-constant. Unlearned live
variation must not silently enter neural feature dimensions. This remains a
prospective adapter concern; no trained live model is running now.


## Continuation: all fits complete, validation replay running, input contract audited (2026-10-31)

All12 v2 fits completed; workflow now brain_impulse_evaluate.py, fold0/base replay.
No validation PnL result yet and no proven edge. MainPID5443 remains running.
Added isolated brain_impulse_feature_contract.py (not wired into frozen competition
or existing live controls). It derives exact constant channels from training rows
only, projects copies of model inputs, and preserves raw timing/freshness evidence.
Near-constant but varying channels are retained. Validation changes block freezing.
Two focused unit tests pass; previous full206-test run remains the latest full run.
Actual audit completed exit0 under CPU100%/MemoryMax3G; retained run.py, contracts
and result under storage/impulse-feature-contract-audit-v1. Both folds have seven
constant channels: OI change/known, funding/known, long/short liquidation logs (0),
receipt_delay_ms (250). Projection changes ZERO windows over118477 and188611
score-validation rows. Data beyond first14days were not loaded by this audit.
Report copied to docs/brain-impulse-feature-contract-2026-10-31.json.
This is prospective adapter preparation, not evidence of profit, not proof of
live distribution equivalence, and not permission to ignore actual receipt lag.
Future trained PAPER must explicitly freeze/integrate this contract AFTER gates;
no trained live model or automatic promotion exists. Existing services untouched.
