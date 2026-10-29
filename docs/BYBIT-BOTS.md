# Bybit bot mechanisms reviewed — 2026-10-29

This is a comparison of documented mechanisms, not a verified ranking of named
live bots. The publicly readable marketplace did not expose sufficient comparable
realized PnL, equity drawdowns, trade histories and execution latency to identify
the fastest or most profitable individual bot. No leader's performance is invented.

| Mechanism | Relevant idea | Limitation for this project |
|---|---|---|
| Spot Grid | Range trading; require the spacing of a completed cycle to exceed costs | Multiple orders divide a $15 account; current minimum notionals may make many grids infeasible |
| Futures Grid | Range/direction selection, explicit stops, total-equity accounting | Funding, leverage and liquidation must be simulated before comparison to spot |
| Aurora parameter suggestions | Compare yield, trade frequency and drawdown across parameter sets | Vendor win-rate claims are not independent out-of-sample evidence |
| Trailing grid | Adapt the trading range with price; stop beyond explicit boundaries | Following a persistent adverse trend can increase inventory exposure |
| Futures Martingale | Frequent realized winning rounds can hide a growing open loss | Increasing losing positions is not implemented; it cannot be called low-risk scalping |

The useful shared principle is **net full-account return with controlled loss**,
not maximum trade count or annualized APR. Grid profit can be positive while the
total account loses money. APR annualizes a short observation and is not promised
future yield. A bot's frequency is also not its exchange execution latency.

Applied now: recurring parameter comparison, mean holding minutes and trades/day,
cost-aware TP/SL labels, fixed loss exits, validation-based selection, and higher
slippage stress tests. We have not implemented or claimed faithful replication
of a native Bybit grid/Aurora/Martingale bot. No limit fill is assumed from merely
touching a candle price. Minute OHLC is insufficient for queue position, order-flow
imbalance or sub-minute execution benchmarking.

Sources (official Bybit):

- [Marketplace](https://www.bybit.com/en/tradingbot/)
- [Grid PnL and APR formulas](https://www.bybit.com/en/help-center/article/P-L-Calculations-Futures-Grid-Bot)
- [Spot Grid market regimes and investment limits](https://www.bybit.com/en/learn/bybit-trading-bot/spot-grid-bot-market-conditions)
- [Trailing grid behavior](https://www.bybit.com/en/help-center/article/How-Trailing-Up-and-Trailing-Down-Work-in-Futures-Grid-Bot)
- [Martingale mechanism and risks](https://www.bybit.com/en/help-center/article/Introduction-to-Futures-Martingale-Bot)
- [Aurora announcement, December 2023; marketing claims, not independent validation](https://www.bybit.com/en/press/post/bybit-launches-aurora-ai-revolutionizing-bot-trading-for-all-investors-bltff16e9d26e99c9a2)

News sources: [Bybit announcement API](https://bybit-exchange.github.io/docs/v5/announcement),
[CoinDesk RSS](https://www.coindesk.com/arc/outboundfeeds/rss/),
[Federal Reserve releases](https://www.federalreserve.gov/feeds/press_all.xml).
