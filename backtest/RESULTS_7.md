# Round 7: can NB3's edge be improved? Not convincingly

Pre-registration: `SHORTLIST_7.md`. Code: `lab7.py` (tests in `tests/test_lab7.py`; the NB3 rule
reproduces round 5's 10-year numbers exactly), `run_round7.py`. Results: `results_round7/`.

## What was tried (128 rule sets x 4 index futures, chosen on 2016-22, checked once on 2023-26)

Ideas from the paper NB3 descends from (Zarattini, Aziz & Barbon 2024, "Beat the Market"):
* gap-adjusted noise bands;
* half-hour signal checks;
* a trailing exit on a close back through max(band, VWAP);
* a high-volatility regime filter;
* trading QQQ, SPY, IWM and DIA together (as MNQ, MES, M2K, MYM).

Plus: band width 1.0 / 1.5, 1 or 2 trades a day, and round 6's tight-stop bracket.

## Results (Sharpe of daily R; R per trade; micro-futures costs)

| | 2016-22 (choice) | 2023-26 (check, once) | All 10 years |
|---|---|---|---|
| **NB3 V2 (QQQ)** | 0.85, +0.079R, 6/7 years up | **1.96, +0.185R**, 4/4 | 1.20, +0.112R, 10/11 years up |
| Pick Q: band 1.5, gap-adjusted (QQQ) | **1.45, +0.184R, 7/7** | 1.10, +0.133R, 4/4 | 1.34, +0.167R, 11/11 (partly in-sample) |
| Pick P: band 1.5, half-hour checks, 4-future portfolio | 0.58 | 0.60 | - |
| NB3 V2 on the 4-future portfolio | 0.12 | 0.96 | - |

## Verdict (pre-registered rule: beat NB3 V2's check-period Sharpe on the same instruments)

**Not improved.**

* **Pick Q:** the wider, gap-adjusted band looked much better on 2016-22 and earns more per trade
  over 10 years. But on the unseen 2023-26 it made less than NB3 V2 (+0.133R vs +0.185R per trade,
  Sharpe 1.10 vs 1.96). It also trades about 45% less often, which slows prop-account payouts.
* **Other index futures do not share the edge:**
  * 2016-22: SPY was weak, and IWM and DIA were flat or negative.
  * 2023-26: IWM and DIA were negative.
  * Adding them diluted QQQ.
* **The paper's trailing exit, the half-hour checks and the volatility filter:** none beat the fixed
  0.3 ATR / 3R bracket.

Stage 2 (Lucid simulation of the picks) was not run, because neither pick passed the check. NB3 V2
on QQQ/MNQ stays the strategy. Round 5's steady setting stays the recommended Lucid configuration.
