# Round 4 ("70% at 1:3" hunt): pre-registered grid and selection rule

Committed BEFORE the round-4 development grid is run (`backtest/run_grid4.py`, `backtest/lab4.py`).

## Goal and the arithmetic

* User's goal: reward:risk 1:3 with a 70% win rate, or better. That is +1.8R per trade before costs.
* In a market with no edge, a +3R target is reached before a -1R stop 25% of the time; costs push that
  lower. Every result is reported two ways:
  * **win rate:** net R > 0. This includes trades closed at 15:55 with a small profit.
  * **target-hit rate:** the full +3R was reached. This is what "70% at 1:3" means literally.
* Baseline from round 3: NB3 V2 (QQQ) won 45% with a 3R target hit on 11% of trades, +0.195R per
  trade over all 675 trades.

## Ideas tested (sources in RESULTS_4.md)

| Family | Idea | Parameters |
|---|---|---|
| `crt` | Candle Range Theory on the first 30 / 60 minutes: sweep one side, close back inside | m = 30, 60 |
| `pdsw` | prior-day high/low sweep, close back inside | - |
| `judas` | Judas swing / Power of 3: early false move beyond the open, close back through it before 11:30 | k = 0.5, 1.0 sigma |
| `ict22` | ICT 2022 model: sweep, displacement fair value gap, retrace entry | level = prior day / 09:30-10:00 range; window = until 11:30 / all day |
| `nrorb` | NR7 / NR4 / inside-day + opening-range breakout | filter x m = 5, 15, 30 |
| `orbrv` | "stocks in play" ORB (Zarattini et al.): first-bar relative volume | k = 1.5, 2, 3; first candle / later breakout |
| `turtle` | turtle soup: failed new 10/20-day extreme (old extreme 4+ sessions back) | n = 10, 20 |
| `va80` | Market Profile 80% rule: open outside value area, re-entry held for k bars | k = 2, 6 |
| `hgrail` | Holy Grail style: daily trend, pullback to VWAP | strength x = 0, 2% |
| `lhh` | last-half-hour momentum (Gao et al. 2018), entry 15:30 | first half-hour / day return; th = 0, 0.5% |
| `gapgo` | gap-and-go with first-bar relative volume >= 1.5 | gap = 0.5%, 1% |
| `odrive` | opening drive: 15-minute range >= k ATR, close in its outer 20% | k = 0.25, 0.4 |
| `nb3` | NB3 V2 signal + one confluence filter | none, VWAP side, daily trend, with / against gap, relative volume >= 1, ATR below / above its 60-day median, after an NR7 day, beyond the prior-day high/low, before / after 10:35, SPY agrees (QQQ for SPY); first signal only / first passing signal |
| `smt` | SMT divergence across 13 correlated pairs: session-high version and prior-day-sweep version | pairs listed in run_grid4.py |

* **Stops:**
  * ATR multiple: 0.1 / 0.2 / 0.3 / 0.5. `lhh` uses 0.05 / 0.1 / 0.2. `nb3` uses 0.2 / 0.3 / 0.5.
  * Structural (`struct`), where the family defines one: beyond the sweep, swing or range extreme,
    plus 0.02 ATR, at least 0.05 ATR.
  * A structural setup more than 1 ATR from its level, or already beyond it, is not taken.
* **Trades per day:** 1. Also 2 for `crt`, `pdsw`, `ict22`, `hgrail` and `smt`.
* **Reward:risk:** 1:1, 1:2 and 1:3 are computed. **Selection uses 1:3 only.**
* **Instruments:** the same 18 ETFs and stocks.
* **Pooled rows:** every setting traded on all 18 instruments together.
* **Fills and costs:** unchanged: next-bar open + 2 ticks, stop first within a minute, 15:55 exit,
  $0.005/share per side.

## Periods

* Development 2023-03-01 .. 2024-12-31.
* Holdout 2025-01-01 .. 2026-03-31, run once for the finalists below.
* **Caveat:** the holdout was already used by rounds 2 and 3, and while checking the code I printed
  full-period results (holdout included) for 15 default settings. The grid above was designed before
  that check and was not changed after it. The Yahoo Sep-Nov 2026 data (QQQ, SPY) is the only data no
  round has looked at.

## Selection (dev only, reward:risk 1:3)

* **Eligible:**
  * development trades >= 60 (pooled rows >= 300);
  * average R > 0;
  * total R > 0 in both 2023 and 2024.
* **Finalists:** at most 2 rows per family in each track, de-duplicated.
  * Track A: top 8 by the 95% Wilson lower bound of the dev win rate.
  * Track B: top 8 by the 95% Wilson lower bound of the dev target-hit rate.
  * Track C: top 8 by the t-statistic of the dev average R.
  * Track P: top 3 pooled rows by t-statistic.
  * Reference: NB3 V2 (QQQ, `nb3` none/first, 0.3 ATR).
* **Meta-labeling ("which setups to skip"):**
  * Event pool: dev trades of 16 base settings, pooled over the 18 instruments: crt 30/60 struct,
    pdsw struct, judas 0.5 struct, ict22 pd/all and or30/am struct, nrorb nr7/15 0.2, orbrv 1.5
    bar0/brk struct, turtle 10/20 struct, va80 2 struct, hgrail 0 struct, gapgo 0.5% struct,
    odrive 0.25 struct, nb3 none/first 0.3.
  * Label: 3R target reached.
  * Features at the signal close: setting, instrument, time, direction-signed gap, trend, VWAP
    distance, noise-band distance and SPY move; ATR level and regime; prior-day range; NR7/NR4/inside;
    relative volume; position in the day's range; weekday; day of month; stop distance.
  * Model: gradient-boosted trees, scikit-learn `HistGradientBoostingClassifier` (depth 3,
    learning rate 0.05, 300 iterations, min leaf 100).
  * Thresholds: the 90th and 97th percentiles of 4-fold expanding-window out-of-fold dev scores.
  * The model is refit on all of dev and applied once to the holdout. Two finalists: trades above
    each threshold.
* **The holdout is run once.** Every finalist is reported with n, win rate, target-hit rate (both
  with 95% intervals), average R, profit factor and per-year R.
* **"Goal met"** only if a finalist's holdout win rate is >= 70% at 1:3 with n >= 50. The target-hit
  rate is stated alongside it.
