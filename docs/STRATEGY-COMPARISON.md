# Hypothesis comparison — 2026-10-29

The supplied chat proposed impulses, reversals, BTC/ETH lead-lag, order flow,
news and adaptive ML. The previous paper agent only used own-symbol candle
features. This run adds fixed rule hypotheses and GPU cross-asset ML candidates.

Data: aligned, real five-minute Bybit spot candles for BTC, ETH and SOL, about
30 days. First 60% train; next 20% validation; last 20% final test. Models train
once per split with a purged 12-bar outcome horizon. No threshold optimization
on the final period. The rules are hypotheses, not accepted market facts.

Mean net percentage returns across three separately funded $15 symbol tests:

| Hypothesis | Validation | Final test | Test trades |
|---|---:|---:|---:|
| XGBoost own-symbol features | -0.004% | -0.425% | 2 |
| XGBoost + BTC/ETH features | +0.030% | -0.374% | 1 |
| Momentum with volume confirmation | -6.828% | -7.197% | 63 |
| Reversal after a drop | -0.359% | -1.403% | 11 |
| BTC/ETH lead-lag | -0.182% | -0.117% | 1 |

Cross-asset XGBoost won validation but lost on the final period and has only one
test trade. It was **not promoted**. The small sample and costs provide no basis
to claim profitability. These are rough candle simulations: no historical spread,
liquidity constraints or historical minimum-order filters. A mean across symbol
tests is not a shared-portfolio return.

The dashboard exposes the actual curves and these limits. It does not generate
trades just to animate a chart. Next useful research is longer regime-diverse
history, label/holding-period alignment and better execution data. News and order
flow require new datasets; candles alone do not reconstruct those signals.

Validation: 17 tests cover data, accounting, future-feature isolation, control
authorization and pause behavior. Desktop/mobile browser checks show five strategy
rows, working symbol/strategy selectors, no JS errors and no horizontal overflow.
The Telegram PNG renderer was executed; delivery/control end-to-end still needs
an owner-authorized Telegram user ID.
