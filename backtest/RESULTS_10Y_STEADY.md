# 10-year backtest of the Lucid "steady" setting (2016-01 .. 2026-03)

**Setting:** NB3 signal on QQQ, executed as MNQ; 0.3 ATR stop; 1.5R target; up to 2 trades a day; $350 risk
budget, at most 3 MNQ.

**Costs:** 1 MNQ tick of slippage per market or stop fill, and $1.50 per round turn.

**Script and results:** `backtest_10y_steady.py`, results in `results_round5/backtest_10y_steady*.json`.

## 1. Trades (R after costs)

| Year | Trades | Win | 1.5R hit | Avg R | Total R | PF |
|---|---|---|---|---|---|---|
| 2016 | 324 | 46.0% | 30.6% | +0.028 | +9.2 | 1.06 |
| 2017 | 355 | 45.6% | 30.1% | -0.019 | -6.7 | 0.96 |
| 2018 | 369 | 48.2% | 34.4% | +0.087 | +32.1 | 1.18 |
| 2019 | 343 | 46.1% | 32.1% | +0.071 | +24.2 | 1.15 |
| 2020 | 355 | 47.9% | 31.8% | +0.100 | +35.4 | 1.21 |
| 2021 | 372 | 44.1% | 28.2% | +0.024 | +9.0 | 1.05 |
| 2022 | 380 | 46.3% | 28.7% | +0.036 | +13.6 | 1.07 |
| 2023 | 367 | 45.2% | 31.9% | +0.041 | +15.1 | 1.08 |
| 2024 | 371 | 46.9% | 33.7% | +0.105 | +38.8 | 1.22 |
| 2025 | 346 | 49.1% | 31.2% | +0.116 | +40.1 | 1.26 |
| 2026 Q1 | 92 | 51.1% | 31.5% | +0.150 | +13.8 | 1.35 |
| **All** | **3,674** | **46.7%** | **31.3%** | **+0.061** | **+224.5** | **1.12** |

* 10 of 11 years were positive.
* The Yahoo check of Sep-Nov 2026 (70 trades) gave +0.157R a trade.

## 2. Plain account ($50,000, $350 risk a trade, no prop-firm rules)

* **Total: +$55,633.**
* **Years:** every year positive except 2017 (-$86); best 2024 (+$11,501).
* **Max drawdown:** -$6,164, ending 2022-02-07.
* **Days:** worst -$692, best +$1,017.

## 3. LucidFlex 50K accounts in date order (no resampling)

* **Method:** a new $130 account is bought whenever one ends.
* **Rules:** the bot's rules: the $800 daily loss limit, the $1,200 best-day cap in evaluation, the funded
  scaling plan, and payouts while keeping $500 above the limit.

| | Accounts | Passed | Paid | Payouts | To you | Net after fees |
|---|---|---|---|---|---|---|
| Halt when the worst case would leave < $100 (old rule), historical volatility | 38 | 14 | 10 | 16 | $12,983 | **+$8,043** |
| **Trade until the limit (new Lucid rule), historical volatility** | 27 | 13 | 11 | 24 | $19,201 | **+$15,691** |
| Halt rule, today's volatility | 49 | 21 | 10 | 13 | $9,979 | **+$3,609** |
| **Trade until the limit, today's volatility** | 33 | 17 | 12 | 22 | $17,298 | **+$13,008** |

**The fix that came out of this backtest:**
* The old rule froze every account once it got near the limit. All 38 accounts ended that way,
  including funded accounts right after a payout, which keep only $500 of room.
* A frozen account cannot recover, and failing a LucidFlex account costs nothing beyond its fee.
* So the Lucid profile (`halt_near_limit = false`) and the TradingView script ("Keep trading near the loss
  limit", on by default) now trade until the limit is actually hit.
* The default for other profiles is unchanged.

**What these figures are:** one historical path, not a promise. Two thirds of the net came in 2018, 2020
and 2024-26; 2016-17 and 2019 lost money on accounts.

## 4. Can several accounts at once make the first payout come sooner? (`ladder_lucid.py`)

* **Rule check:** LucidFlex allows 10 evaluation and 5 funded accounts at once, and trade copiers are
  permitted (help centre, 2026-11-17).
* **Method:** programs started on every 5th trading day of 2016-01 .. 2025-03, each run for 12 months.
* **Ladder K:** a new account every month until K are running; failed ones are replaced the next day.

Today's volatility:

| Program | Paid within 6 months | Paid within 12 months | Median months to the first payout | Fees | Net in 12 months, mean / median | Net per $1 of fees | Ahead |
|---|---|---|---|---|---|---|---|
| One at a time | 38% | 72% | 5.8 | $498 | +$722 / +$265 | 1.45 | 62% |
| 2 at once | 39% | 73% | 5.6 | $964 | +$1,344 / +$510 | 1.39 | 61% |
| 3 at once | 39% | 73% | 5.6 | $1,398 | +$1,847 / +$613 | 1.32 | 59% |
| 5 at once | 40% | 74% | 5.6 | $2,169 | +$2,598 / +$920 | 1.20 | 58% |

**Result: barely faster.**
* Accounts started a month apart trade the same market, so they tend to pass and fail together.
* Running more of them scales the money, both payouts and fees, roughly in proportion.
* It does not bring the first payout much closer: the median goes from 5.8 to 5.6 months.
* Historical volatility gives the same picture.
