# Home server access

Verified 2026-10-29. Local repository: `D:\w_spase\cripto_staff`.
Remote repository: `https://github.com/fermiums22/cripto_staff.git`.

## Network

Windows WireGuard profile `codex-home` starts automatically. It routes only
`192.168.0.2/32` and `192.168.0.8/32` through the home VPN. Normal internet and
DNS use the office network. Profile files are outside Git in
`C:\Users\v.taranov\.ssh\codex-network`.

The old full-tunnel profile `fermiums` is stopped and its service startup is
Manual. **Do not activate both profiles together:** they reuse one VPN identity.
This is a separate routing profile, not a separate VPN peer or independent relay.

## Verified SSH path

Run in the repository root from PowerShell:

```powershell
ssh -T -i .\work-pc-to-codex-home_ed25519.txt -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=5 root@192.168.0.2 'hostname; pct list'
```

The real private key filename ends in `.txt`. It is intentionally ignored by
Git, as are its extensionless and public-key variants. Do not print its contents.
The key needs Windows ACL permissions restricted to its owner.

Proxmox host: `pve`, `root@192.168.0.2`. Observed ED25519 host-key fingerprint:
`SHA256:c2X6nG9ksMO7wqAjrAOJ0ebsr6hZRYzFblnmnd7elBM`.
The fingerprint was accepted on first connection, not independently authenticated.

Development container: CT **103**, name `codex-home`, IP `192.168.0.8`.
Workspace: `/home/codex/workspace`; regular user: `codex`.
Direct SSH authentication to `codex@192.168.0.8` has not been configured.
Use the verified Proxmox path:

```powershell
ssh -T -i .\work-pc-to-codex-home_ed25519.txt -o IdentitiesOnly=yes -o BatchMode=yes root@192.168.0.2 'pct exec 103 -- runuser -u codex -- id'
```

For multiline commands, avoid nested Windows/Linux shell quoting. Pipe a literal
PowerShell here-string containing Python into
`ssh ... root@192.168.0.2 'pct exec 103 -- python3 -'`.
Use `subprocess.run([...], check=True)` inside Python. Run application code as
`codex`; use container root only for installation/service administration.

Read `/home/codex/workspace/AGENTS.md` and relevant sections of
`/home/codex/workspace/CHATGPT-SERVER-CONTEXT.md` before server changes.
Those files may reference credentials: do not copy secrets into this repository.

## Nika pause and recovery

Nika was paused on 2026-10-29. Nika/Qwen services, their timers,
`ha-agent-bridge` and `sokol-learning-consolidator` were stopped; previously
enabled units were disabled. Models remain in place. The service named
`qwen-chat` was actually running a Ministral model at the time of inspection.

CT 103 backup directory:
`/root/config-backups/nika-pause-20261029T070626Z`.

It contains a private configuration/source/memory archive, original unit states,
model path/size inventory, SHA256 checksum, verification record, and `resume.py`.
Gzip CRC and both archived SQLite databases passed verification. Large model
files and virtual environments were not duplicated. The backup is on the same
server, not an off-server disaster recovery copy.

Restore previously enabled/running services from Proxmox:

```bash
pct exec 103 -- python3 /root/config-backups/nika-pause-20261029T070626Z/resume.py
```

This restores service state without replacing current memory with old data.
Restore script syntax was checked; a full restart was intentionally not performed.

GPU: RTX 5070, 12227 MiB VRAM; usage dropped from 9779 MiB to 0 MiB after pause.
Check on Proxmox with `nvidia-smi`. The container has GPU devices, but no
`nvidia-smi` command on its default PATH.

## Services to preserve

- VM 100: Home Assistant.
- VM 101: TrueNAS.
- CT 102: VPN gateway.
- CT 105: home-edge.
- CT 103: browser workspace and shared Codex services.

Do not stop the entire development container to stop a single application.

## Trading project

Source: `/home/codex/workspace/cripto_staff`, owned by `codex`.
Service: `cripto-paper.service` (experimental spot simulation, no real orders).
Windows status: `powershell -ExecutionPolicy Bypass -File .\status.ps1` from the repository root.
GPU training requires `LD_LIBRARY_PATH=/opt/nvidia-driver`; the main paper
service performs CPU inference. Nika remains paused.

Downloads must use direct home internet, not VPN. The verified CT 103 default
route is `192.168.0.1` on `eth0`; remove proxy environment variables for download
processes. Do not change the remote-access tunnel to accelerate downloads.

Bybit credentials: `secrets/bybit.key` in the project directory, mode 0600,
parent directory 0700. Local source `crypto_cey` is ignored by Git. First line is
the label, then API key and secret. Never print the file or raw authenticated API
responses. The owner explicitly chose Read-Write permissions; real trading is
still prohibited until separately authorized. `check_api.py` checks authentication
using only GET `/v5/user/query-api` and prints no credential values.

## Dashboard and Telegram

Dashboard: `http://192.168.0.8:8765`, service `cripto-dashboard` in CT 103.
This is a home-LAN/VPN-only read-only endpoint, not a public hosted Site.
Only explicitly allowlisted static paths and `/api/snapshot` are served.
Equity history is in SQLite table `equity`; existing paper balance is preserved.

Telegram service: `cripto-telegram`, bot `@my_home_cripto_bot`.
Token: project `secrets/telegram.token`, mode 0600. Local source: `telega_bot`,
Git-ignored. Never print either file or Telegram API request URLs containing tokens.
Allowlist: `secrets/telegram-access.json`, `user_ids` array of integer IDs.
It is reloaded on each message. Only add IDs supplied/approved by the owner.
Private `/id` works without authorization, everything else requires the allowlist.
Do not call `getUpdates` manually while the service polls it.

Pause/resume sets SQLite state `control.paused`. The agent keeps running to
manage existing simulated positions. No root, systemctl or shell execution is
available through Telegram. Paused entries remain paused across restarts.

Hypothesis comparison: `strategy_lab.py`, GPU environment as above. It writes
`artifacts/comparison.json` and never replaces `artifacts/models.json`.

## Scheduled research and context

`cripto-research.timer`: daily 00:15 UTC / 03:15 Minsk; first run started manually.
`cripto-research.service`: `research_worker.py`, minute data in `data/research.sqlite3`,
progress in `artifacts/research_status.json`, latest result in `search_result.json`.
CPUQuota=200%, MemoryMax=4G, timeout two hours. No automatic model promotion.
`cripto-context.timer`: every fifteen minutes, public news/announcements only.
No proxy is used for these HTTP downloads; remote-access VPN remains untouched.

Telegram notification preferences: SQLite `subscriptions`. Delivery attempts:
`deliveries` with sent/unknown/sending state. Only allowlisted recipients receive
notifications, and each opts in independently. Do not reset cursors to replay old
trades or generate fake live events for testing.

## Fast parallel paper strategies

`cripto-arena.service` runs `paper_arena.py` as codex, polling quotes about every
five seconds. Six independent $15 accounts persist in `arena_accounts`, with
curves in `arena_equity` and heartbeat in `state.arena_status`. Do not reset them
to conceal losses. Each position has a 60–180 second time limit, checked only
on fresh quotes; outages can delay exits. Global `control.paused` blocks entries.
Common `events` include strategy identifiers and feed opted-in Telegram users.
Dashboard refreshes every five seconds and compares net equity, closed trades,
holding time and current state. Real trading remains disabled.

## Read-only real execution audit

`python fee_audit.py --symbol AAVEPERP` reads personal fee rates, orders,
executions, positions, transaction ledger and public funding/quotes. USDC
display names can differ from API symbols: AAVEUSDC is AAVEPERP. Resolve other
symbols through instruments-info. Only allowlisted GET endpoints are supported.
On the workstation use `--credentials crypto_cey`; never print credentials.
Timestamped private reports go to ignored `artifacts/fee-audits/`. They cover
the previous 24 hours and follow pagination; this command is not a monitor.
Keep ledger funding separate from USDC session P&L. Execution fees and ledger
fees may describe the same charge: do not add both. Positive ledger funding
means received; positive ledger fee means paid. Empty records are not evidence
of no charges if a request failed or the ledger is delayed. No orders are sent.

Arena v2 adds three separate accounts (`leadlag_cost_v2`, `breakout_cost_v2`,
`rebound_cost_v2`), preserving all six original histories. They require a
continuous three-minute quote window, movements exceeding explicit cost filters,
and 30 seconds between exits and new entries. Holding limit remains 180 seconds.
The BTC variant uses the current fresh BTC quote, not the previous sample.
Filters describe past moves, not expected future returns. New account age differs
from old accounts: compare per-trade results and observation time, not just equity.
All nine are still spot paper strategies; USDC futures fees must not replace spot
fees. No claim of improvement is justified until forward observations arrive.

`arena_backtest.py` reads the latest aligned 30 days from research.sqlite3 and
atomically writes artifacts/arena_backtest.json for the dashboard. It is a
minute-close proxy of the three v2 rules, not an exact tick replay. Signals use
closed bars, entries use next opens, ambiguous OHLC exits choose stop first.
Assumed full spreads: 0.02% base, 0.06% stress; fee/slippage remain spot assumptions.
No tuning or auto promotion; history was already inspected in earlier research.
Historical curves are separate from persistent live accounts. Run as codex with
the project Python; no GPU or new downloads are required except current lot rules.

`waiting_research.py` evaluates six fixed spot-long variants: dip, dip with volume,
dip with volume and BTC regime; TP .6%/1%, SL twice TP. No time exit, but positions
are liquidated at each evaluation boundary and included in PnL. First 20 days
select (minimum 20 trades), last 10 evaluate plus wider-spread stress. Previously
examined history is not pristine holdout. No automatic promotion or short/leverage.
Output artifacts/waiting_research.json appears separately on the dashboard.
The six original arena variants and breakout_cost_v2 are retired: no new entries,
existing positions still exit normally, all balances and event histories retained.
