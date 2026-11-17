# Round 6: pushing NB3 for fast Lucid Flex payouts (tight stops, pullback entries, big size)

Pre-registration: `SHORTLIST_6.md`. Code: `lab6.py` (tested in `tests/test_lab6.py`; market entries
match `lab4.bracket` exactly on 675 / 1,096 real trades), `run_lucid6.py`, `lucid6_stress.py`.

* **Setting:** today's volatility; Lucid Flex 50K rules including the funded scaling plan (20 / 30 /
  40 micros); up to 5 accounts bought one after another ($650).
* **Search:** 25,088 settings scored on 2016-22. The picks were checked once on 2023-26.

## What pushing the limits found

* **Tight stops help, a little:** NB3's best per-trade results on 2016-22 use **0.075-0.10 ATR**
  stops: +0.13R vs +0.10R at 0.30 ATR, with MNQ costs.
* **Size is what makes payouts fast:** a tight stop lets you hold 5-10 MNQ for the same dollar risk.
  This works only up to a point: speed mostly comes from bigger swings, and a good part of it is
  luck (see the no-edge rows).
* **"Top/bottom" pullback limit entries hurt.**
  * The best version paid within 3 months 25% of the time, vs 57% for normal entries.
  * At 0.10 and 0.20 ATR pullbacks, no setting kept positive 12-month cash.
  * The pullbacks that fill are mostly the moves that fail; strong moves never come back to your
    order.
* **Breakeven stops after +1R:** no improvement (56% vs 57%).

## Picks, checked once on 2023-26 (up to 5 accounts, 2,000 runs)

| | Paid within 1 month | 3 months | 6 months | 12 months | Ahead after 12 months | Cash after 12 months: mean / median |
|---|---|---|---|---|---|---|
| **B: fast** (0.1 ATR stop, 2R, 1/day, $500 / $500, keep $500) | 7% | **45%** | 59% | 60% | 55% | **+$1,424** / +$153 |
| A: fastest (0.1 ATR, 1R, $1,000 / $500, keep $0) | **17%** | **55%** | 57% | 57% | 37% | +$372 / -$128 |
| C: balanced (0.1 ATR, 1.5R, $700 / $500, keep $0) | 12% | 51% | 57% | 57% | 45% | +$706 / -$117 |
| Round 5 "steady" (0.3 ATR, 1.5R, 2/day, $350 / $350, keep $500) | 0% | 11% | 43% | **79%** | **73%** | +$1,309 / **+$676** |
| Current bot (0.3 ATR, 3R, 1/day, $350 / $250, keep $2,000) | 0% | 1% | 11% | 43% | 43% | +$508 / -$130 |

**Robustness, paid within 3 months / ahead after 12 months / mean cash:**

| | 2023-26 half edge | 2016-22 half edge | No edge (luck only) | 2023-26, 3 ticks of slippage |
|---|---|---|---|---|
| B: fast | 37% / 45% / +$739 | 34% / 42% / +$556 | 27% / 32% / +$159 | 43% / 50% / +$1,155 |
| A: fastest | 49% / 32% / +$182 | 48% / 30% / +$61 | 41% / 24% / -$92 | 48% / 32% / +$168 |
| Round 5 steady | 6% / 47% / +$378 | 4% / 40% / +$159 | 2% / 25% / -$152 | 9% / 67% / +$968 |

## Reading it

* **The fastest realistic setting is B:**
  * NB3 entry, stop 0.1 ATR (about $90 per MNQ today), target 2R, one trade a day;
  * $500 risk, about 5 MNQ, in both phases;
  * payout as soon as allowed, keeping $500.
* **What B delivers:**
  * Half of the 5-account runs get paid within 3 months; the median first payout is about 2 months
    (43 trading days).
  * B typically uses all 5 accounts within the year.
  * Its median result is only slightly positive, and with half the edge the median run loses all
    $650.
* **The steady alternative is round 5's setting:**
  * slower: typically 4-6 months to the first payout;
  * but the most consistent: 73% ahead after a year, median +$676.
* **Luck vs edge:** with no edge at all, B still gets paid within 3 months 27% of the time and is
  slightly positive on average. Lucid's rules cap your loss at the fee while paying real money, so
  big swings are rewarded. That speed is luck, not skill, and it varies a lot from person to person.

## Not modelled

* QQQ is the proxy for NQ. Tight stops (about 40 NQ points) are more sensitive to small path
  differences and to fast-market slippage; 3 ticks were tested.
* News-event restrictions.
* Lucid price changes; $130 is assumed.
* The DLL-on version (cheaper, intraday payouts) and the 50%-consistency add-on.
* Live accounts after 5 payouts.
* The bot does not implement B or the round-5 setting yet.
