# Pre-registered finalists (committed before any holdout evaluation)

Development period: 2023-03-01 .. 2024-12-31 (Rrishab/OHLCV-1m, split-adjusted).
Locked holdout: 2025-01-01 .. 2026-03-31, evaluated once per finalist after this file is committed.
Variants tried on development data before this choice: 58, all logged in `research_log.csv`.

| # | Finalist | Rules | Dev result (cost model: 2 ticks + $0.005/share per side) |
|---|---|---|---|
| 1 | QQQ intraday momentum | `index_momentum.run(ticker="QQQ", band_mult=1.0, use_vwap=True)`, published defaults | Sharpe 1.71, 412 trades, 41.7% trade win rate, 2023 +11.4%, 2024 +7.1% (unlevered) |
| 2 | SPY intraday momentum | same rules on SPY | Sharpe 0.88, 435 trades, 40.9%, 2023 +4.9%, 2024 +2.4% |
| 3 | Stock ORB "E04" | top 20 by RVOL (>= 1), stop-order entry at the 5-min range edge, stop at the other side of the range, skip if stop < $2.00, flat at 15:55 | +0.015R/trade, 1,679 trades, 47.0% win rate, 13/22 positive months |

Selection rule for reporting: all three are reported on the holdout, whatever the outcome. No parameter
changes after this commit.
