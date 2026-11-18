# Round 9: top/bottom ticking with standard deviations and ICT OTE, on gold (pre-registered)

Committed BEFORE the round-9 grid is run (`backtest/run_round9.py`, `backtest/lab9.py`).

## Instruments

* **Gold:** GLD 1-minute data executed as Micro Gold MGC, approved at Lucid, $0.80 a side. Assumptions:
  gold = 10.8 x GLD; 10 oz contract; one $0.10 tick of slippage per market or stop fill; $1.60 a round
  turn.
* **Second market:** the Nasdaq, QQQ executed as MNQ, with round-5 costs.
* **Hours:** New York regular hours only. The data has no London session.

## Families (58 settings per instrument)

* **VWAP standard-deviation fades.** Entry: a 5-minute close beyond VWAP +/- k SD ("close"), or a wick
  beyond it with the close back inside ("reject"). k = 2 / 2.5 / 3.
* **ICT standard-deviation projections.** The 09:30-10:00 range extreme +/- k ranges, k = 2 / 2.5 / 4;
  rejection entries.
* **For both of these:**
  * signals from 10:00 to 14:50, up to 2 trades a day;
  * stop beyond the signal bar's extreme (+0.02 ATR, 0.05-1 ATR), or 0.2 ATR;
  * target VWAP or the range midpoint (0.5-4R), or a fixed 1R / 2R.
* **ICT OTE.** The first hour's impulse (the 10:30 close vs the open). A limit order at a 70.5% or 61.8%
  retracement works until 14:30. Stop beyond the leg's origin; target the leg's end, or the -27%
  extension. 1 trade a day.

## Selection (design 2016-01 .. 2022-12; check 2023-01 .. 2026-03, run once)

* **Metric:** Sharpe of daily R after costs.
* **Eligible:**
  * >= 200 design trades;
  * >= 5 of 7 design years positive;
  * design Sharpe > 0.
* **Picks:**
  * P1-P3: the three best eligible settings, any instrument;
  * PG: the best eligible gold setting, if none of P1-P3 is gold.
* **Verdicts (check period):**
  * "works": Sharpe > 0.5 and mean R > 0;
  * "beats NB3 steady": Sharpe > 1.57.
* **Diversification:** for every pick, the correlation of its daily R with NB3 steady's, and the Sharpe of
  the two added together (equal risk) vs NB3 steady alone (1.57).
