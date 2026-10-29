# Bybit research and paper agent

Experimental **spot, long-only** agent. It consumes real Bybit market data;
public means no account authentication, not synthetic data. No real orders or
account-changing API calls are implemented. The owner's $40,000 goal is a project
motivation, not a forecast or a promised result.

## Current implementation

User hypotheses and requirements: [original rules 1–8 and learning goals](docs/USER-TRADING-IDEAS.md).

- BTCUSDT, ETHUSDT, SOLUSDT: 30 days of closed five-minute Bybit spot candles.
- GPU XGBoost training (`device=cuda`); CPU fallback fails explicitly.
- Three chronological evaluation windows with a purged label horizon; cash and
  buy-and-hold comparisons. Final paper model is trained on all available labels.
- Live paper portfolio: **$15 total**, one position, at most 90% allocation.
- Entry at observed ask plus 5 basis points slippage; exit at bid minus 5 basis
  points. Assumed fee: 0.1% each side. Exchange minimum entry order and quantity
  precision checked. TP 1.5%, SL 1%, maximum holding period one hour.
- SQLite persistence, duplicate-signal prevention and error/heartbeat logs.

Paper trading is an explicitly experimental run, **not an approved profitable
strategy**. Models with poor historical results are still visibly evaluated in
this sandbox. Real money remains disabled.

## Run

Python 3.13 environment on CT 103:

```bash
cd /home/codex/workspace/cripto_staff
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
LD_LIBRARY_PATH=/opt/nvidia-driver .venv/bin/python agent.py research
.venv/bin/python agent.py run
```

Run downloads without VPN/proxy: the container default route is the home router
`192.168.0.1`; public-data HTTP explicitly ignores proxy environment settings.
Do not switch the VPN used for remote access. If a download environment supplies
proxy variables, remove them for that process only.

Research outputs: `artifacts/research.json`, `artifacts/models.json`.
Market data, simulated accounting and events: `data/agent.sqlite3`.
These files, `.env`, and `crypto_cey` are ignored by Git. The supplied three-line
credential file (name, API key, secret) is stored privately on the server at
`secrets/bybit.key`. `python check_api.py` verifies authentication and prints only
permission flags. Per the owner's choice the key has Read-Write permissions;
this does **not** authorize real orders. The paper process does not read the key.

## Service and inspection

Live dashboard on the home LAN/VPN: **http://192.168.0.8:8765**.
It shows real prices, live paper equity, model decisions, events and independent
strategy comparisons. It is read-only, serves no credentials, and is not exposed
to public internet. The graph starts when equity recording was added; earlier
equity is not invented. Model scores are not calibrated success probabilities.

Telegram: **https://t.me/my_home_cripto_bot**. In a private chat, `/id` returns
the sender's numeric user ID. All other commands require that ID in the private
`secrets/telegram-access.json` file (`{"user_ids": [123]}`). Only owner-approved
IDs should be added; do not authorize usernames or automatically trust the first
sender. Empty allowlist denies all trading information and controls.

Commands: `/status`, `/chart`, `/pause` (also `/stop`), `/resume`.
Notifications: `/notify_on` and `/notify_off` (also keyboard buttons), independently
for each allowlisted account. Default off. Enabling starts at the latest event;
old trades are not replayed. Messages explicitly say PAPER and include net exit
PnL and exit reason. Delivery attempts persist in SQLite; uncertain network
deliveries are recorded as `unknown` and not blindly resent, so a message may be
missed during an outage. The dashboard/events remain the accounting source.
Pause blocks new virtual entries but continues exits and market collection.
Commands cannot submit real orders, change leverage, or execute shell commands.
Telegram remains online while entries are paused. Browser graphs are accessible
only on the home network/VPN; Telegram `/chart` sends a PNG without needing VPN.
The token is stored in `secrets/telegram.token`; local `telega_bot` is Git-ignored.

Services: `cripto-paper`, `cripto-dashboard`, `cripto-telegram`. Source units live
in `deploy/`. The web service binds only to the private container address.

Run a separate GPU hypothesis comparison with:

```bash
LD_LIBRARY_PATH=/opt/nvidia-driver .venv/bin/python strategy_lab.py
```

It compares XGBoost, cross-asset BTC/ETH features, momentum, reversal, and lead-lag
rules. Training uses the first 60%, validation the next 20%, final test the last
20%, with purged labels at the train boundary. Model selection uses validation;
the test is not used for tuning. Results go to `artifacts/comparison.json`.
The running paper model is not automatically replaced by a candidate.

## Autonomous research and news

`cripto-research.timer` runs daily at 03:15 Europe/Minsk. `research_worker.py`
resumes a separate 90-day, one-minute spot history for BTC/ETH/SOL/XRP/DOGE.
It trains 30 GPU models: three TP/SL/holding configurations, own-symbol or
cross-asset features, five symbols. Three probability thresholds produce 18
candidate configurations. Labels use the same adverse-first TP/SL execution
as the candidate simulator. UTC hour and weekday features are included.
Selection uses the middle 20% validation period; only the selected configuration
is evaluated on the final 20%, including a double-slippage stress run. Daily
periods overlap, so repeated tests are not independent confirmations.
Mean returns combine separate $15 symbol accounts, not a shared portfolio.

Results: `artifacts/search_result.json`; progress: `artifacts/research_status.json`;
saved selected weights and reports: `artifacts/search-runs/<UTC timestamp>/`.
The live paper model remains unchanged. This is a finite, scheduled parameter
search, not a claim of unrestricted autonomous strategy invention or profitability.
Research limits: two CPU cores, 4 GiB RAM, two hours per run. GPU allocations are
bounded by the selected model/data sizes, without a hardware VRAM quota.

`cripto-context.timer` collects Bybit announcements, CoinDesk RSS and Federal
Reserve releases every 15 minutes. It stores headline/link/publication time and
immutable first-seen time in `data/context.sqlite3`. Simple topic classification
is displayed in the dashboard. News is observation-only until a prospective
study validates its incremental value; no historical news is retroactively made
available to the model. No weather/astrological causal signal is assumed.

See [Bybit bot research](docs/BYBIT-BOTS.md) for sources and mechanism comparisons.

Install `deploy/cripto-paper.service` into CT 103's `/etc/systemd/system/` after a
successful research run. Then `systemctl enable --now cripto-paper`.

From Proxmox:

```bash
pct exec 103 -- systemctl status cripto-paper --no-pager
pct exec 103 -- journalctl -u cripto-paper -n 20 --no-pager
pct exec 103 -- runuser -u codex -- /home/codex/workspace/cripto_staff/.venv/bin/python /home/codex/workspace/cripto_staff/agent.py status
```

Access from Windows is documented in [docs/SERVER.md](docs/SERVER.md).
Quick Windows status: `powershell -ExecutionPolicy Bypass -File .\status.ps1`
(policy override for this process only; system settings remain unchanged).
Verified initial results: [docs/FIRST-RUN.md](docs/FIRST-RUN.md).
Stop only the agent with `pct exec 103 -- systemctl stop cripto-paper`.

## Validation and current limits

```bash
python -m unittest discover -s tests -v
```

Tests cover completed candles, invalid data, feature causality, missing bars,
adverse TP/SL ordering, stop gaps, next-bar historical execution, costs, minimum
orders and duplicate prevention across reconnects.

Historical simulation is approximate: it has fixed slippage but no historical
spread, liquidity constraints or historical lot-size rules; each symbol's test
uses a separate $15 account. The baseline live sandbox uses one shared $15 portfolio.
Live stops are checked every 30 seconds and can be crossed during outages.
Stale data prevents new signals; missed signals are not filled retroactively.

No derivatives, leverage, funding, RL, news or historical order-book features
yet. Cross-asset features are research candidates, not the live model.
GPU is used during training; live inference runs on CPU. Retraining is
explicit, not an automatic replacement of the running model.

Data contracts: [Bybit candles](https://bybit-exchange.github.io/docs/v5/market/kline),
[instrument rules](https://bybit-exchange.github.io/docs/v5/market/instrument).
GPU algorithm: [XGBoost documentation](https://xgboost.readthedocs.io/en/stable/gpu/).

## Fast live paper comparison

`paper_arena.py` runs six experimental spot rules independently: best-price size
imbalance, momentum, breakout, rebound, mean reversion and BTC lead/lag. Each has
its own persistent virtual $15 account. Quotes are polled approximately every
five seconds; positions exit on TP/SL or after 60–180 seconds when a fresh quote
is available. Network delays can extend holding time; this is not HFT.

Dashboard comparison and Telegram trade notifications identify each strategy.
Global pause blocks new entries in both the arena and baseline. Existing
positions keep being managed. Each account stops entering at $12 cash or less.
Trades include observed spread, assumed 0.1% fee and 0.05% slippage per side.
Entry checks best-ask size; fills and exit depth are still simulated. These are
unvalidated experiments, not profitable models. No private/order API is used.
Market contract: [Bybit tickers](https://bybit-exchange.github.io/docs/v5/market/tickers).
