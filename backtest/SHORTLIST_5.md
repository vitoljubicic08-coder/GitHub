# Round 5: 10-year test of NB3 V2, and the best way to get paid by a Lucid Flex account

Committed BEFORE either test is run (`backtest/run_lucid5.py`, `backtest/lucid5.py`).

## Part 1: NB3 V2 on 7 years it has never seen

* **Data:** the same public 1-minute dataset as rounds 1-4 (Hugging Face "Rrishab/OHLCV-1m"), QQQ
  2016-01-04 .. 2023-02-28. No earlier round used these years.
* **Rules:** NB3 V2 exactly as in the bot: band 1.0, first signal of the day, signal bars opening
  09:30-14:50, stop 0.30 ATR, target 3R, exit at 15:55. Costs are the research costs: 2 ticks of
  $0.01 plus $0.005 per share per side.
* **Reported:** for each year and for the whole new period: trades, win rate, 3R hit rate,
  average R, t-statistic, profit factor.
* **Verdict for 2016-01 .. 2023-02 (decided now):**
  * "confirmed": average R > 0 with t >= 2.0;
  * "weak": average R > 0 with t < 2.0;
  * "failed": average R <= 0.

## Part 2: Lucid Flex 50K ($130 one-time): maximise the chance of getting paid

* **Rules:** as in `prop_sim.FIRMS["lucid"]`, summarised in `lucid5.py`.
  * Evaluation: +$3,000, with a $2,000 end-of-day trailing limit that is breached in real time and
    stops at +$100. The best day must be <= 40% of the profit.
  * Funded: a payout needs 5 days of +$150 or more. It can be 50% of profit, at most $2,000 and at
    least $500. The split is 90%, and the account moves to live after 5 payouts.
* **Signal:** NB3 V2's entry signal on QQQ, executed as MNQ. Costs: 1 tick of slippage and $1.50
  per round turn; $82.6 per QQQ dollar per contract.
* **Grid** (5,376 settings):
  * Exits: stop 0.2 / 0.3 / 0.4 ATR x target 1R / 1.5R / 2R / 3R x 1 or 2 trades per day. With 2
    trades, the second is the next NB3 signal after the first trade closes.
  * Evaluation sizing:
    * risk budget $250 / $350 / $500 / $700 per trade;
    * or 10% / 15% / 20% / 30% of the distance to the loss limit.
  * Funded sizing:
    * risk budget $150 / $250 / $350 / $500;
    * or 10% / 15% / 20% of the distance to the loss limit.
  * Whole MNQ contracts only. A trade whose single contract exceeds the size is skipped.
  * Payout requests: the maximum as soon as eligible, or only what keeps $500 / $1,000 / $2,000
    above the post-payout loss limit.
* **Design data:** 2016-01 .. 2022-12, never used for any choice.
  * 2,000 lifecycles per setting, each a new $130 account.
  * 10-day block bootstrap; 252 trading days (12 months).
  * The same random day sequences for every setting.
* **Objective:** the probability that one $130 account pays at least one payout within 12 months.
* **Picks:**
  1. the highest objective;
  2. the highest expected net cash per account over 12 months;
  3. "balanced": the highest expected net among settings within 2 points of the best objective.
* **Check, run once:**
  * the three picks, plus the bot's current setting as baseline (stop 0.3, 3R, 1/day, $350 / $250,
    keep $2,000);
  * scored on 2023-01 .. 2026-03 with the full edge and with half the edge;
  * and on the design data with half the edge.
* The 2023-26 period is where NB3 was designed. It is out of sample for these risk and payout
  choices, not for the signal.

## Part 2b (added after Part 2's check, before running it): the same search at today's volatility

* **Why:** Part 2's dollar sizes assume each period's own volatility. Today one MNQ at a 0.3-ATR stop
  risks about $275 (real NQ data, Sep-Nov 2026). That is 1.8 times the 2023-26 median, so the
  "$250" picks of Part 2 cannot place a single contract today (`lucid5_curvol.py`).
* **Rescaling:** in each period, every trade's dollar risk per MNQ is multiplied by one factor. The
  factor makes the period's median 0.3-ATR one-MNQ risk equal $275.3. Outcomes in R are unchanged.
* **Grid, objective, picks and check:** identical to Part 2.
  * Design: 2016-2022, rescaled.
  * Check, run once: 2023-26 rescaled, with full and half edge, and design rescaled with half edge.

## Outcome (added after the runs; details in RESULTS_5.md)

* **Part 1:** 2016-01..2023-02: +0.049R per trade, t = 1.44 over 1,629 trades. Verdict: **weak**.
* **Part 2:** the balanced pick (NB3 V2 exits, $250 / $250, keep $500) won every check: 72% vs 51%
  paid within 12 months on 2023-26. Its $250 budget would skip most trades at today's volatility.
* **Part 2b:** the pick at today's volatility is stop 0.3 ATR, 1.5R, up to 2 trades/day, $350 / $350,
  keep $500.
  * Paid within 12 months: **40.6%** vs 32.7% for the bot's setting on 2023-26.
  * Half the edge: 23.1% vs 14.5%. 2016-22 with half the edge: 18.9% vs 6.7%.
