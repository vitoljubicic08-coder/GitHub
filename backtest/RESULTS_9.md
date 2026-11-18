# Round 9: top/bottom ticking with standard deviations and ICT OTE on gold. Result: no edge

Pre-registration: `SHORTLIST_9.md`. Code: `lab9.py`, `run_round9.py`. Results: `results_round9/`.

**Data:** gold is GLD 1-minute data (2016-2026) executed as Micro Gold, MGC. It is approved at Lucid at
$0.80 a side, per the help centre on 2026-11-18. The Nasdaq (QQQ -> MNQ) was the second market.

## Design 2016-2022 (58 settings per market)

| Family | Best gold Sharpe | Best Nasdaq Sharpe |
|---|---|---|
| ICT SD projection of the 09:30-10:00 range, rejection fade (-2 / -2.5 / -4 SD) | -0.06 | +0.12 (47 trades) |
| VWAP +/- 2-3 SD, close-beyond fade | -0.54 | +0.20 (32 trades) |
| VWAP +/- 2-3 SD, wick-rejection fade | -1.06 | -0.49 |
| ICT OTE (61.8 / 70.5% of the first-hour impulse) | -1.62 | -1.13 |

* **Gold:** none of the 58 settings was positive.
* **Nasdaq:** 2 were slightly positive, on too few trades to count.
* **Outcome:** no setting met the eligibility rule (>= 200 trades, >= 5 of 7 years positive, positive
  Sharpe). So, as pre-registered, nothing went to the 2023-26 check.

**Information only, chosen in hindsight:** the best gold setting of each family on 2023-26 had Sharpe
-0.72 / -0.51 / -0.16 / -0.11. All negative.

## Why it fails

* **Fading is a bet against the trend.** Standard-deviation fades and wick rejections buy weakness and
  sell strength within the day. In these markets intraday moves tend to continue, which is the effect
  NB3 profits from.
* **Gold during the session:** it trended strongly in the New York session, especially through the
  2024-26 rally.
* **OTE:** it fills mainly on deep pullbacks. The pullbacks that fill are mostly the moves that are
  failing, the same adverse selection seen in rounds 6 and 8.

## Not covered

* Gold's London session and the 08:20 COMEX open. The data has only New York regular hours.
* Discretionary, chart-read versions of these setups.
