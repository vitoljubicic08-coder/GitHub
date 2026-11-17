# Round 8: dealer gamma, VIX, Fed days, order flow, standard deviations, ICT OTE

Pre-registration: `SHORTLIST_8.md`. Code: `lab8.py` (tests in `tests/test_lab8.py`), `run_round8.py`,
`fetch_round8_data.py`. Results: `results_round8/`.

* **Setup:** each idea was applied to the Lucid "steady" setting (NB3 signal, 0.3 ATR stop, 1.5R, up to
  2 trades a day, MNQ costs). Ideas were chosen on 2016-22 and checked once on 2023-26.
* **Metric:** Sharpe of daily R.

## Results

| Idea | 2016-22 (choice) | 2023-26 (check) | Verdict |
|---|---|---|---|
| **Base (Lucid steady)** | 0.78 | **1.57** | |
| Trade only with the opening gap | 1.07 (all 7 years up) | 1.51 | not improved |
| VIX above its 1-year median | 1.01 | 1.10 | not improved |
| Dealer gamma below its median | 0.93 | 0.90 | not improved |
| Gap + VIX together | 1.11 | 1.17 | not improved |
| **ICT standard-deviation target** (09:30-10:00 range extreme + 2 ranges, 1-4R) | 0.98 | **1.84** (+0.14R vs +0.09R a trade) | **improved** |
| Negative dealer gamma | -0.43 | - | worse; it goes against the published claim |
| ICT OTE entries (61.8% / 70.5% retracement) | -1.2 to -1.9 (0-1 of 7 years up) | - | badly worse |
| Order-flow proxies (relative volume, close location, delta, divergence) | 0.43-0.86 | - | no real effect |
| VWAP standard-deviation filters | 0.77-0.84 | - | no real effect |
| Skip Fed days / only Fed days | 0.82 / -0.15 | - | no real effect |

## Does the improvement help on Lucid? No

One $130 account at today's volatility (round 6 model):

| | Paid within 12 months, 2023-26 | Mean cash | Paid within 12 months, 2016-22 | Mean cash |
|---|---|---|---|---|
| Base | 42.1% | +$634 | 30.4% | +$373 |
| Standard-deviation target | 41.6% | +$621 | 26.5% | +$334 |

**Why it does not help:**
* The projection target gives bigger but rarer wins (1-4R).
* Lucid pays only after 5 winning days, and caps each payout.
* So the better Sharpe does not turn into more payouts.

It may suit a regular account. For Lucid, the steady setting stays.

## Information only

**Overnight:** LucidFlex closes all positions at 4:45 pm ET, so overnight holds are impossible there. QQQ's
close-to-open drift was:
* 2016-22: +3.2 basis points a night (Sharpe 0.57);
* 2023-26: +6.0 basis points (Sharpe 1.24).

This is a known effect, usable only in a personal account.

**Data notes:**
* Sources: dealer gamma from SqueezeMetrics GEX; VIX / VIX3M from Yahoo; Fed dates from federalreserve.gov.
* CPI dates are missing, because BLS refuses automated downloads.
* Order flow is approximated from 1-minute OHLCV (there is no bid/ask data).
