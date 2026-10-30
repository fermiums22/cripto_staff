# Adaptive shared-wallet PAPER: verified delivery, 30 October 2026

Dashboard: http://192.168.0.8:8765/adaptive (home LAN/VPN).
Service: `cripto-adaptive.service`; public market GET requests only, no credentials
or exchange order functions. The service cannot read the project's secrets directory.
Old dashboard sections, histories and PAPER services remain in place.

## Implemented and observed

- One persistent $15 wallet, one selected coin/direction at a time. The engine
  accounts for quantity/tick/minimum constraints, taker fees, settled funding,
  isolated-margin liquidation approximation, gap stops, cooldown and a 30% loss
  halt. Stops can overshoot the halt in gaps; it is not a guaranteed loss cap.
- Past-only BTC/ETH lead-lag, volume impulse, exhaustion short, regime continuation,
  timestamp-seeded random-direction waiting, and combined signal candidates.
  Strength/confidence is a heuristic move proxy, not a calibrated probability.
- Early TP versus next-bar trailing. Risk sizing, 1/3/10 leverage controls and
  at most one winning-position addition are implemented in simulations. Live
  PAPER is restricted to 1x without additions.
- Training: 2026-07-31 22:45 to 2026-09-23 14:30 UTC; validation to 2026-10-11
  14:30 UTC; test to 2026-10-29 14:30 UTC. 24 candidates; selection persisted
  before the test. All periods liquidate their positions at their boundaries.
- Data audit: 20 aligned linear 15m symbols; five spot 1m histories with no
  timestamp gaps; retained public stream sessions for 45 symbols. Spot prices
  were not substituted for derivative execution/mark prices.
- Frozen candidate: `leadlag_trail_0.003`. Train $10.5483; validation $12.4074.
  Both lost money. The live profitability gate is **closed**. The running service
  collects quotes, computes candidates and preserves $15; it opens no positions.
- Service observed fetching fresh quotes/features for all 20 symbols. A SQLite
  transaction preserves wallet, funding cursor and signal cursor together.

| Frozen test scenario | Final wallet | Net | Fees | Max drawdown | Trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| Realistic assumptions | $12.6677 | -$2.3323 | $1.4458 | 20.21% | 72 |
| Optimistic friction | $15.0112 | +$0.0112 | $1.3521 | 12.00% | 67 |
| Severe stress | $10.3494 | -$4.6506 | $1.4050 | 31.31% | 55 |

None reached $30, $100 or $2000. The 10x control produced two modeled
liquidations/bankruptcies; it is not deployed. Pyramiding was supported but no
eligible addition occurred in the selected test (not evidence of benefit).
Gross, net, fees, funding, MFE/MAE, rejection counts, excursions and trade records
are in `artifacts/adaptive_research.json`. The frozen selection and source/data
hashes are in `artifacts/adaptive_protocol.json`; current state is in
`artifacts/adaptive_live.json` and `data/adaptive.sqlite3`.

## Verified versus limitations

Server suite: 78 tests passed at initial deployment, including 15 adaptive engine
and HTTP tests. Covered past-only features, next-observation decisions, gaps,
stop/TP ordering, trailing timing, liquidation, fees/funding reconciliation,
rounding, shared capital, winning additions, persistence, stale quotes and the
public-only endpoint allowlist. JavaScript syntax and read-only HTTP endpoints
passed. Browser screenshot execution was blocked by automatic policy review;
visual desktop/mobile QA is not claimed.

History was already examined by earlier research. The chronological test is not
a pristine holdout. Universe selection uses currently surviving/liquid assets;
historical listing and rule changes are not fully reconstructed. SOL fees reuse
the prior verified maker .00036 / taker .001 report; other coins use scenario
fees. All new simulated fills are taker. Market-order price-limit/depth rejection,
queue position, historical rule changes and exchange liquidation mechanics are
not fully modeled. MFE/MAE exclude ambiguous exit bars. Polling can miss intrabar
extremes; live funding uses the observed mark, not an archived settlement mark.

Hypotheses 1–4 and 7–10 have explicit candidates/controls. Volume and regime
removal are evaluated on validation only; removing an unused feature can have
no effect. Stream imbalance is measured only in actual retained sessions and
does not count participants. A validated microstructure trading model, paired
website/API latency study (5), and point-in-time news ablation (6) remain blocked
by insufficient suitable history. No profitability or completion of those
experiments is claimed.

Public API specifications checked:
[instrument constraints](https://bybit-exchange.github.io/docs/v5/market/instrument),
[funding](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate),
[candles](https://bybit-exchange.github.io/docs/v5/market/kline).

## Source preservation

The home scripts, workstation simulator changes, ranker/microstructure research
and local tests are preserved in a separate Git commit before this implementation.
Those pre-existing experiments were not rewritten or promoted to the new bot.
Drive D: ran out of free space during implementation. The complete working copy
is `C:\Users\v.taranov\cripto_staff-adaptive`; the original directory and source
snapshot were retained. No user data was deleted to free space.

Operational checks: `systemctl status cripto-adaptive`,
`journalctl -u cripto-adaptive`; pause entries through the existing global PAPER
pause. Restarting the service does not reset the wallet or change the selection.
`python adaptive_research.py` preserves an existing frozen report; it never
silently reruns or tunes the holdout. Training a new version requires an explicit
new protocol and future evaluation window.
