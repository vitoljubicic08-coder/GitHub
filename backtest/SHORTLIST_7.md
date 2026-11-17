# Round 7: improving NB3's edge (pre-registered)

Committed BEFORE the round-7 grid is run (`backtest/run_round7.py`, `backtest/lab7.py`).

## Ideas

Taken from the paper NB3 descends from: Zarattini, Aziz & Barbon (2024), "Beat the Market: An
Effective Intraday Momentum Strategy for S&P500 ETF (SPY)".

* **Gap-adjusted noise bands:** the upper band from max(open, previous close), the lower band from
  min(open, previous close).
* **Half-hour checks:** look for signals only at :00 / :30 closes.
* **Trailing exit:** leave on a close back through max(band, VWAP) (min for shorts), instead of a
  fixed target.
* **More instruments:** trade the same rule on several index futures at once.
* **Regime filter:** trade only when volatility is at or above its 60-day median, since intraday
  momentum is reported to be stronger in volatile markets.

## Grid (128 rule sets)

* band 1.0 / 1.5 x gap adjustment off / on x checks every 5 minutes / at :00 and :30 x all days /
  high-volatility days only;
* x exit: bracket 0.3 ATR / 3R (NB3), bracket 0.1 ATR / 2R (round 6), trail with a 0.3 or a
  0.1 ATR hard stop;
* x 1 or 2 trades a day.

**Instruments** (executed as micro futures: one futures tick of slippage per market or stop fill,
$1.50 per round turn):
* QQQ as MNQ, the mapping verified on real futures;
* proxies: SPY as MES, IWM as M2K, DIA as MYM.

**Portfolio:** all four, equal risk per trade, measured as the sum of R per day.

## Selection (design = 2016-01 .. 2022-12; check = 2023-01 .. 2026-03, run once)

* **Pick P:** the highest design Sharpe of the daily portfolio R, with at least 5 of 7 design years
  positive.
* **Pick Q:** the same, on QQQ alone.
* **Baseline:** NB3 V2 (band 1.0, no gap, 5-minute checks, all days, 0.3 / 3R, 1 trade a day).
* **"Improved" means:** the pick's check-period Sharpe beats the baseline's on the same instrument
  set.

## Stage 2 (after the check)

* Picks P and Q go into the Lucid Flex simulator: today's volatility, funded scaling plan, up to 5
  accounts in sequence.
* **Per-trade risk budget:** $150 / $250 / $350 / $500, chosen on design by the chance of being ahead
  after 12 months. Payouts are taken as soon as allowed, keeping $500.
* **Contract cap:** the total across concurrent positions is capped (40 micros in evaluation; 20 / 30
  / 40 when funded).
* **Edge haircut:** the "half edge" case subtracts a constant from every trade's R.
* **Comparison:** against round 5's steady setting under the same model, on 2023-26 with the full
  and half edge.

## Outcome (added after the check; details in RESULTS_7.md)

* **Pick Q** (band 1.5, gap-adjusted, QQQ): design Sharpe 1.45 vs 0.85, but **check 1.10 vs NB3
  V2's 1.96. Not improved.**
* **Pick P** (portfolio, band 1.5, half-hour checks): check 0.60 vs NB3 V2 portfolio 0.96. **Not
  improved.**
* **SPY, IWM and DIA** add no reliable edge.
* **Stage 2** was not run, because no pick passed.
