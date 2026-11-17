# Round 5: NB3 V2 over 10 years, and the setting that gets a Lucid Flex account paid most often

Pre-registration: `SHORTLIST_5.md` (committed before each part was run). Code: `run_lucid5.py`,
`lucid5.py` (tested against `prop_sim.run_stream` in `tests/test_lucid5.py`), `lucid5_curvol.py`.
Raw results: `results_round5/`.

## Part 1: 7 new years (2016-01 .. 2023-02). Verdict: **weak**

* **New period:** NB3 V2, unchanged, on 1,629 trades it had never seen, made **+0.049R per trade**
  (t = 1.44, profit factor 1.09). That is below the pre-registered "confirmed" bar of t >= 2. With
  micro-futures costs it is +0.076R (t = 2.2).
* **The years it was built on:** 2023-03 .. 2026-03 made +0.191R. Over the full 10 years it is
  +0.091R (t = 3.15) on 2,316 trades.

| Year | Trades | Win rate | 3R hit | Avg R | t |
|---|---|---|---|---|---|
| 2016 | 213 | 38.0% | 9.4% | -0.008 | -0.08 |
| 2017 | 232 | 37.5% | 9.0% | -0.101 | -1.16 |
| 2018 | 225 | 41.8% | 15.1% | +0.167 | 1.64 |
| 2019 | 225 | 43.6% | 7.1% | +0.047 | 0.56 |
| 2020 | 231 | 40.3% | 7.8% | +0.056 | 0.63 |
| 2021 | 228 | 40.4% | 8.8% | +0.092 | 0.99 |
| 2022 | 237 | 42.2% | 8.0% | +0.108 | 1.18 |
| 2023 | 231 | 42.0% | 7.8% | +0.090 | 0.97 |
| 2024 | 226 | 42.5% | 11.9% | +0.178 | 1.85 |
| 2025 | 211 | 48.3% | 10.4% | +0.224 | 2.36 |
| 2026 (Q1) | 57 | 47.4% | 15.8% | +0.369 | 1.83 |

Research costs: 2 x $0.01 slippage + $0.005/share. Full table, including MNQ costs: `results_round5/nb3_10y.md`.

**Meaning:**
* The edge is real but smaller than 2023-26 suggested: positive in 9 of 11 years, about +0.05 to
  +0.10R in a typical year.
* 2023-26 was its best stretch. Plan with about a third to a half of the 2023-26 edge.

## Part 2: Lucid Flex 50K ($130, one-time). Which setting gets paid most often?

* **What was searched:** 5,376 settings combining:
  * exits: stop 0.2 / 0.3 / 0.4 ATR x target 1 / 1.5 / 2 / 3R x 1 or 2 trades a day;
  * evaluation sizing x funded sizing;
  * payout requests.
* **Simulation:**
  * 2,000 accounts per setting, each simulated for 12 months.
  * Lucid's exact rules: the real-time trailing loss limit, the 40% consistency rule, payouts after
    5 days of +$150, the $500 minimum and $2,000 cap, and live after 5 payouts.
* **Selection:** settings were chosen on 2016-2022, then checked once on 2023-2026.

**Part 2, with each period's own volatility.** The balanced pick raised the payout chance in every
check: 72% vs 51% on 2023-26, and 39% vs 23% with half the edge. But it trades on a $250 budget, and
the two other picks use a 0.4-ATR stop. At today's volatility all three would skip most or all
trades (`results_round5/check_current_vol.json`).

**Part 2b, at today's volatility (pre-registered after Part 2).** Today one MNQ at NB3's stop risks
about $275, 1.8 times the 2023-26 median. Every trade's dollar risk was rescaled to that level and
the same search was rerun.

**The pick, "Lucid-optimized":**
* **Entry:** the NB3 V2 signal, unchanged.
* **Exits:** stop 0.3 ATR, target **1.5R**, flat by 15:55.
* **Second trade:** **up to 2 trades a day** (the next NB3 signal after the first trade closes).
* **Sizing:** a $350 risk budget in both phases. That means whole MNQ = floor($350 / one MNQ's
  risk):
  * 1 MNQ at today's volatility;
  * 2 on calm days, when one risks <= $175;
  * no trade when one risks more than $350.
* **Payouts:** request one as soon as eligible, keeping at least **$500** above the $50,100 loss
  limit.

**Results for one $130 account:**

| | Paid within 12 months, 2023-26 | Within 6 months | Median days to first payout | Mean net cash per account (12 months) |
|---|---|---|---|---|
| Bot's current setting (1:3, 1/day, $350/$250, keep $2,000) | 32.7% | 9.4% | 160 | +$453 |
| **Lucid-optimized** | **40.6%** | **32.0%** | **86** | **+$603** |

**Robustness:**

| | 2023-26, half the edge | 2016-22, half the edge | 2016-22, no edge (pure luck) |
|---|---|---|---|
| Bot's current setting | 14.5% | 6.7% | 2.2% |
| Lucid-optimized | **23.1%** | **18.9%** | 10.9% |

## Why it works

* **Win days:** Lucid pays only after 5 winning days of +$150 or more. NB3 at 1:3 reaches its
  target on only 10% of trades, and most of its "wins" are small 15:55 exits that do not count. A
  1.5R target is hit much more often and turns into qualifying win days. The second trade a day adds
  more chances.
* **Payouts:**
  * A $2,000 cushion delays the first payout by months, and many accounts blow up before reaching
    it.
  * Asking early, keeping $500, gets cash out of the account sooner.
  * The trade-off is fewer payouts per account in the long run. Over 24 months the current setting
    earns more per surviving account: +$1,423 vs +$583 on 2023-26.
* **Edge vs luck:** with no edge at all, the optimized setting still pays 11% of accounts. That is
  the lottery part of a $130 account. The edge lifts it to about 19-41%.

## What to expect

* **Per account:** about **1 in 5 to 2 in 5** $130 accounts should produce a first payout within a
  year: 19-23% if the edge is half of 2023-26's, which the 10-year test suggests is realistic, and
  41% if 2023-26 repeats. Cost per payout is roughly $130 / p, so $320-$690.
* **Mean result:** positive in every pre-registered check, from +$117 to +$603 per account (net of the
  $130).
  The **median account still loses its $130**.
* **Not modelled:**
  * Lucid rule changes after 2026-11-17;
  * real NQ fills (QQQ is used as the proxy, with per-trade correlation 0.996 on 2026 data);
  * days with news-related trading restrictions;
  * what happens after the move to live.
* **The bot:** it does not yet implement the 1.5R / 2-trades-a-day variant or this payout rule. That
  is a separate change, which would need its own parity tests.

## Reproduce

```
INST=<10-year cache: build_candidate_cache.py --market-only, 2016-01..2026-03>
python3 backtest/run_lucid5.py --inst $INST nb3
python3 backtest/run_lucid5.py --inst $INST design && python3 backtest/run_lucid5.py --inst $INST check
python3 backtest/run_lucid5.py --inst $INST design_now && python3 backtest/run_lucid5.py --inst $INST check_now
NB3_INST=<inst cache> python3 -m unittest tests.test_lucid5
```

## Follow-up: how many accounts until you are ahead? (`lucid5_accounts.py`, `results_round5/accounts_needed.json`)

* **Model:**
  * Accounts are bought one after another. When one fails, blows up or moves to live, the next
    $130 account starts the following trading day, up to a budget.
  * Only cash counts: payouts received minus fees paid.
  * Today's volatility, Lucid-optimized setting, 2,000 simulated runs per row.

| Scenario | Budget | P(ahead) after 12 months | P(ahead) after 24 months | Median cash after 24 months | Mean cash after 24 months |
|---|---|---|---|---|---|
| 2016-22 repeats (10-year test, realistic) | 3 accounts ($390) | 58% | 68% | +$301 | +$1,240 |
| | 5 accounts ($650) | 56% | 71% | +$947 | +$1,746 |
| | 10 accounts ($1,300) | 56% | 75% | +$1,167 | +$1,868 |
| 2023-26 repeats (optimistic) | 3 accounts | 75% | 82% | +$1,010 | +$2,025 |
| | 5 accounts | 73% | 87% | +$2,201 | +$2,941 |
| 2023-26 at half its edge (pessimistic) | 3 accounts | 49% | 54% | +$103 | +$651 |
| | 5 accounts | 47% | 58% | +$318 | +$1,010 |
| No edge (luck only) | 5 accounts | 25% | 31% | -$650 | +$46 |

* **Time limits the count:** a failed account takes about 2-3 months to play out, so one year fits
  only 3-4 accounts in a row. A budget above 3 helps only over 24 months.
* **Which account pays:** the first payout typically comes from the 1st or 2nd account.
