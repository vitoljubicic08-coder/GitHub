# Round 8: dealer gamma, VIX, Fed days, order flow, standard deviations, OTE (pre-registered)

Committed BEFORE the round-8 grid is run (`backtest/run_round8.py`, `backtest/lab8.py`).

## Base

The Lucid "steady" setting:
* NB3 signal on QQQ, executed as MNQ;
* 0.3 ATR stop, 1.5R target, up to 2 trades a day;
* costs: 1 MNQ tick of slippage and $1.50 per round turn.

NB3 V2 (3R, 1 a day) is reported alongside it for information only.

## Ideas (each one changes only which signals are traded, or how)

Day filters use only what is known before the open: the previous day's values, and the Fed calendar,
which is published in advance.

* **Dealer gamma** (SqueezeMetrics GEX, previous day). Background: Baltussen et al. (2021) report
  that intraday momentum is stronger when dealers are short gamma.
  * below its 1-year median;
  * in its bottom third;
  * negative.
* **VIX** (previous close):
  * at least 20;
  * above its 1-year median;
  * VIX >= VIX3M (backwardation);
  * VIX / VIX3M >= 0.9.
* **Fed (FOMC) statement days:** skip them, or trade only them. CPI days could not be tested, because
  BLS refuses automated downloads.
* **Order-flow proxies** (1-minute OHLCV only, no bid/ask; "delta" = volume x close location):
  * signal-bar relative volume >= 1.5, and >= 1;
  * the signal bar closes in its outer 40% in the trade's direction;
  * cumulative delta agrees with the trade;
  * no delta divergence (a new session extreme with delta lagging).
* **Standard deviations:**
  * entry within 2 VWAP standard deviations (not overextended);
  * entry beyond 1 VWAP standard deviation (confirmed);
  * targets at ICT-style projections of the 09:30-10:00 range, range extreme +/- 1 or 2 ranges,
    between 1R and 4R.
* **ICT OTE entry:** limit order at a 70.5% or 61.8% retracement of the session's impulse leg up to the
  signal bar, working for 60 minutes. The stop goes beyond the leg's origin. The target is the
  leg's end, or the -27% extension.
* **Other:** with or against the opening gap; with the prior-day trend; signals before / after 10:35.
* **Overnight / multi-day:** not tradable on LucidFlex, which closes every position at 4:45 pm ET. The
  close-to-open drift of QQQ is reported as information only.

## Selection (design = 2016-01 .. 2022-12; check = 2023-01 .. 2026-03, run once)

* **Metric:** annualised Sharpe of daily R (0 on days without a trade), net of costs.
* **Eligible:**
  * >= 300 design trades;
  * >= 5 of 7 design years positive;
  * design Sharpe above the base's.
* **Picks:**
  * P1-P3: the three best eligible filters;
  * P4: P1 AND P2;
  * P5: the best eligible entry/exit variant (standard-deviation targets or OTE).
* **"Improved" means:** the check-period Sharpe beats the base's check-period Sharpe.
* **Lucid check:** improved picks are run through the LucidFlex simulator at today's volatility (round 6
  model, one $130 account): the chance of a payout within 12 months, and mean cash.

## Outcome (added after the check; details in RESULTS_8.md)

* **Picks:** P1 gap-with, P2 VIX above median, P3 gamma below median, P4 P1 + P2, P5 standard-deviation
  target (k = 2).
* **Check Sharpe:**
  * base 1.57;
  * P1 1.51, P2 1.10, P3 0.90, P4 1.17 (not improved);
  * **P5 1.84 (improved)**.
* **Lucid:** P5 did not raise the payout chance: 41.6% vs 42.1% on 2023-26, and 26.5% vs 30.4% on
  2016-22.
* **ICT OTE entries and negative dealer gamma:** clearly worse.
