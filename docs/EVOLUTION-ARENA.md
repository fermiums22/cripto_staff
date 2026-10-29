# Evolution arena — first working stage

Separate research module: `evolution_env.py`, `evolution_research.py`.
No private API, orders, changes to live strategy weights, Telegram accounts,
or Nika services. All accounts are simulated, starting with **$15 each**.

## Implemented experiment

- SOLUSDT linear futures, 21 days of public minute trade/mark OHLC and funding.
  Closed bars only; no inferred order book or claims of second-level precision.
- First 14 days train, next 3 select, final 4 evaluate frozen candidates.
  Normalization fits training data only. XGBoost labels end before selection.
  Some overlapping history was inspected in previous experiments: this is not
  a pristine external holdout. Test results must not guide retuning this run.
- PPO from Stable-Baselines3: hold/wait, long, short, close. Two seeds, 32,768
  steps each. Best parent by validation net return minus half maximum drawdown;
  two children inherit its trained weights and optimizer, mutate learning rate
  and entropy, and train 32,768 additional steps. Parent/children/checkpoints
  are preserved. This is bounded sequential selection, not full asynchronous PBT.
- PPO's reward is change in liquidation-cost-adjusted equity, including entry
  and exit fees, funding and mark-to-market losses. No reward for trade counts.
  Position direction, size, unrealized account equity and age enter observations.
- XGBoost regresses the next 30-minute price return; thresholds .32% and .6%
  compete on validation only. Horizons are fixed in this stage. Training uses
  CUDA and fails if the XGBoost config does not confirm CUDA. PPO's small MLP
  runs on CPU as recommended by Stable-Baselines3.
- Trend following (30-minute momentum), 30-minute volatility breakout and cash
  baselines have the same accounting and chronological evaluation.
- Final test, wider-friction stress, two separately funded test subperiods,
  per-agent CSV, curves, drawdown, gross/fees/funding/net, actual weight changes.
- Capital Growth Challenge runs the selected frozen policy continuously through
  the final four days with 50% and 90% position budgets, 1x leverage, no top-ups.
  It does not reset at day boundaries. Separate runs are labelled; this is not
  a shared portfolio or an estimated probability of ruin.

## Execution model

Signal at minute close, action at the following open. One position at a time.
Opposite entry closes the current position, paying both costs. Repeating the
same side holds without resizing. Personal taker fee is loaded from ignored
`artifacts/execution_fees.json`; per-fill friction .06% baseline, .11% stress.
Current exchange lot/minimum-notional rules apply; historical rule changes are
not reconstructed. Funding at bar open applies only to existing positions.

Mark OHLC provides a conservative liquidation proxy (maintenance margin without
tier deductions). Gap liquidation is checked before discretionary orders.
Intrabar adverse mark updates drawdown; equity <= $12 stops at minute close.
Every episode and evaluation boundary closes remaining positions, charges costs
and reports remaining losses. Extreme gaps can produce a negative simulated
balance: no insurance-fund or exchange bankruptcy-price precision is claimed.
Episode reset to $15 is allowed **only during training** (512-minute episodes).
No such reset occurs inside a reported continuous evaluation.

## Reproduce on the server

Read `SERVER.md` for SSH and environment first. Run as codex in the project.
Install CPU PyTorch to avoid unnecessary CUDA package duplication:

```sh
.venv/bin/pip install --no-cache-dir torch==2.7.1 --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install --no-cache-dir -r requirements-evolution.txt
LD_LIBRARY_PATH=/opt/nvidia-driver .venv/bin/python -m unittest discover -s tests -p test_evolution_env.py
LD_LIBRARY_PATH=/opt/nvidia-driver .venv/bin/python evolution_research.py
```

Input: `data/evolution_history.json` (the `window_experiment.collect(21)` schema).
Each run writes immutable-by-convention files under `artifacts/evolution/<UTC>/`:
config, normalization, seed, input SHA256, dependency versions, PPO zip weights,
XGBoost model, validation selection, full report, input history, source snapshots
and CSV trades. Cash wins exact selection-score ties. The latest dashboard
report and status are atomic JSON files, older run folders remain untouched.
Do not run two instances simultaneously; the deployed transient systemd unit
`cripto-evolution` serializes this run. It has CPUQuota=200%, MemoryMax=3G,
Nice=10, RuntimeMaxSec=1800. There is no recurring schedule in this stage.

## Explicitly deferred

SAC/TCN/Transformer, cross-asset and true order-flow features, maker/taker paired
signal replay, tick queue/latency, full leverage/insurance/liquidation tiers,
regime-conditioned meta agent, shared portfolio, automatic forward paper admission
and local Qwen hypothesis generation. Nika remains preserved and paused.
No profitability qualification is inferred from a single selected curve.

## Sources

- [PPO paper](https://arxiv.org/abs/1707.06347).
- [Stable-Baselines3 PPO and CPU guidance](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html).
- [Population Based Training](https://arxiv.org/abs/1711.09846): motivation for
  weight inheritance and hyperparameter mutation, not a claimed full reproduction.
