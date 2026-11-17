# Round 6: aggressive NB3 trade management for fast Lucid Flex payouts (pre-registered)

Committed BEFORE the round-6 grid is run (`backtest/run_lucid6.py`, `backtest/lab6.py`).

## Goal

The user wants Lucid Flex 50K payouts quickly: "take a bit more risk, tighter stops, push the limits".

## Rules

* As in round 5 (`lucid5.py`), plus the **funded scaling plan** from Lucid's help centre (checked
  2026-11-17):
  * funded profit < $1,000: at most 20 micros;
  * < $2,000: 30 micros;
  * otherwise 40;
  * updated at the end of each session.
* **Accounts are bought one after another:** a new $130 account the trading day after one fails,
  blows up or moves live, at most 5 accounts ($650).

## Signal and grid

The signal is NB3 V2's entry signal on QQQ, executed as MNQ, at today's volatility (rescaled as in
Part 2b of round 5).

* **Exit variants** (448):
  * entry: market (next bar), or a limit 0.05 / 0.10 / 0.20 ATR better than the signal close,
    working for 30 minutes, filled only on a trade-through (the "top/bottom" entry);
  * stop: 0.05 / 0.075 / 0.10 / 0.15 / 0.20 / 0.30 ATR, or just beyond the signal candle
    ("bar");
  * breakeven: off, or the stop moves to entry after +1R;
  * target 1 / 1.5 / 2 / 3R; 1 or 2 trades a day.
* **Evaluation sizing:** risk budget $350 / $500 / $700 / $1,000, or 20% / 30% / 50% of the
  distance to the loss limit.
* **Funded sizing:** risk budget $250 / $350 / $500, or 25% of the distance.
* **Payout:** as soon as eligible, keeping $0 or $500 above the loss limit.
* **Total:** 25,088 settings.

## Selection (design = 2016-2022 at today's volatility, 1,000 runs per setting, same random days)

* **Primary:** the chance that at least one payout arrives within **3 months** (63 trading days).
* **Constraint:** mean cash after 12 months (payouts minus fees) > 0.
* **Picks:**
  * (A) the highest primary;
  * (B) the highest mean cash after 6 months;
  * (C) "balanced": the highest mean cash after 12 months among settings within 3 points of A's
    primary.
* **Baselines:**
  * round 5's Lucid-optimized setting (market, 0.3 ATR, 1.5R, 2/day, $350 / $350, keep $500);
  * the bot's current setting (market, 0.3 ATR, 3R, 1/day, $350 / $250, keep $2,000).
* **Check, run once, 2,000 runs:**
  * 2023-26 at today's volatility, full and half edge;
  * 2016-22 with half edge;
  * extra: no edge.
* **Reported:** payout within 1 / 3 / 6 / 12 months, mean and median cash at 6 and 12 months, and
  the chance of being ahead.

## Outcome (added after the runs; details in RESULTS_6.md)

* **Design:** 4,014 of 25,088 settings had positive 12-month cash. Every pick uses market entries
  with a 0.1 ATR stop, one trade a day and large size.
  * A: 1R, $1,000 / $500, keep $0.
  * B: 2R, $500 / $500, keep $500.
  * C: 1.5R, $700 / $500, keep $0.
* **Check, 2023-26, paid within 3 months:**
  * A 55%, B 45%, C 51%;
  * vs 11% for round 5's setting and 1% for the current bot.
* **Check, ahead after 12 months:**
  * B 55% (mean +$1,424, median +$153);
  * round 5 73% (median +$676).
* **Pullback ("top/bottom") limit entries and breakeven stops did not help.**
