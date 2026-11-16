# Round 3 (prop-firm objective): pre-registered selection rule

Committed BEFORE the round-3 development grid is run.

* Objective: the chance of passing a $50K evaluation within one month.
  * Target +$3,000; trailing drawdown $2,000 (closed-trade/EOD style, stops at the starting balance).
  * 21 trading days, at most 2 trades per day, simulated by resampling the period's own days.
* Risk per trade is chosen on development data from {$150, $250, $350, $500, $750} and kept fixed on
  the holdout.
* User target for reference: about 70% one-month pass probability.
* Grid (`backtest/run_grid3.py`):
  * the 24 round-2 signal settings plus 10 new ones (34 in total):
    * prior-day high/low liquidity sweep and fade (ICT)
    * prior-day high/low break
    * fair value gap retest, all day and 10:00-11:00 "silver bullet", displacement 1.5x / 2.0x
    * cumulative-delta divergence (bar-based order-flow proxy), 0.25 / 0.5
    * initial-balance (60-minute) break and failure
  * x stop 0.1 / 0.2 / 0.3 ATR, x 1 or 2 trades/day, x reward:risk 1:0.33 .. 1:3
  * x 18 instruments
* Development 2023-03-01 .. 2024-12-31; locked holdout 2025-01-01 .. 2026-03-31.
  Costs: 2 ticks of slippage + $0.005/share per side.
* Eligible: at least 150 development trades, average R > 0, and positive total R in both 2023 and 2024.
* Finalists, each run once on the holdout with its development risk and all reported:
  1. the 10 eligible combinations with the highest development pass probability;
  2. Portfolio P2: the two highest-ranked eligible 1-trade-per-day combinations on two different
     instruments, traded together (at most 2 trades per day);
  3. reference: NB3 (QQQ noise_break 1.5, stop 0.2, 1/day, 1:3) scored the same way.

## Outcome (added after the holdout run)

* Development: 18,270 combinations, 791 eligible. **None reached a 50% one-month pass probability;
  the best was 45%.**
  * Best by family: noise_break 45%, vwap_break 42%, orb 42%, gap_fade 40%, delta_div 40%,
    orb_fail 39%, vwap_fade 39%, fvg 37%, rsi 37%, pd_break 36%, noise_fade 35%, vwap_pullback 35%,
    pd_sweep 34%.
  * The ICT and order-flow ideas did not beat the existing momentum families.
* Holdout (`grid3_holdout_finalists.csv`): every finalist kept a positive average R. One-month pass
  probabilities were 34-52%.
  * **Best: QQQ noise_break 1.0, stop 0.3, 1/day, 1:3 = 52%** (48% winners, +0.255R, profit factor
    1.55).
  * Portfolio P2 (QQQ 1:2 + TSLA 1:3, 1/day each): 52%.
  * NB3 V1 reference: 36%.
* Independent Yahoo Sep–Nov 2026, QQQ 1.0/0.3/1:3: 52% (+0.249R per trade, profit factor 1.52).
  The same holdout days with the edge removed: 31%.
* Exploratory, not pre-registered:
  * QQQ 1:3 + TSLA 1:3 = 55% on the holdout;
  * QQQ 1:3 + SPY vwap_break 1.0/0.2/1:3 (futures-tradable) = 52%.
* Implemented as **NB3 Breakout V2** (`nb3_breakout_v2_*.pine`): band 1.0, stop 0.3 ATR, 1:3, one
  signal per day, QQQ or TSLA.
* The ~70% target was not reached. It needs roughly +0.35-0.40R per trade at 2 trades per day.
