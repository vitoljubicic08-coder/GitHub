# Round 2 (arrow strategies with fixed reward:risk): pre-registered selection rule

Committed BEFORE the development grid is run.

* Instruments (ETF proxies and large stocks): SPY, QQQ, IWM, DIA, GLD, SLV, TLT, USO, XLE, XLF, SMH,
  AAPL, NVDA, TSLA, AMZN, MSFT, META, AMD. Futures (ES, NQ, GC) are not in the dataset.
* Grid (`backtest/intraday_lab.py`):
  * 24 signal settings across 9 families (VWAP standard-deviation fade/break, noise-band fade/break,
    ORB, failed ORB, RSI extremes, gap fade, VWAP pullback)
  * stop 0.1 / 0.2 / 0.3 x previous daily ATR
  * reward:risk 1:0.33, 1:0.5, 1:1, 1:2, 1:3
  * at most 1 or 2 trades per day
  * 720 combinations per instrument, 12,960 in total
* Development period: 2023-03-01 .. 2024-12-31. Locked holdout: 2025-01-01 .. 2026-03-31.
* Costs: 2 ticks of slippage on entry, stop and end-of-day fills, plus 0.005 USD/share per side.
* A combination is eligible if, on development data, it has at least 200 trades, positive total R in
  both 2023 and 2024, and a profit factor of at least 1.10.
* Finalists, each run exactly once on the holdout and all reported:
  1. the 10 eligible combinations with the highest average R;
  2. the eligible combination with the highest win rate among those with reward:risk >= 1:1;
  3. the eligible combination with the highest win rate at reward:risk 1:3.
* User target for reference: >= 70% win rate at about 1:3 (break-even at 1:3 is 25%).
