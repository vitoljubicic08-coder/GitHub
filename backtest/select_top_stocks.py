#!/usr/bin/env python3
"""Pick the best stocks for SIP-ORB from a trades.csv and check them out of sample.

1. Selection period: rank stocks with at least --min-trades trades by total net R.
2. Report the top N in the later test period, which played no part in choosing them.
3. Full-period top N with results per calendar year (consistency view).
4. Luck benchmark: shuffle all trade results across stocks (keeping each stock's trade count)
   and see how good the full-period top N look when there is no stock-specific edge at all.

Usage:
  python3 backtest/select_top_stocks.py results_hf/trades.csv --split 2025-04-01 --min-trades 10
"""
from __future__ import annotations

import argparse
import csv
import random
import statistics
from collections import defaultdict


def stats(rs: list[float]) -> str:
    if not rs:
        return "   0 trades"
    wins = [x for x in rs if x > 0]
    losses = [-x for x in rs if x <= 0]
    pf = f"{sum(wins) / sum(losses):5.2f}" if losses and sum(losses) > 0 else "  inf"
    return (f"{len(rs):>4} trades  win {100 * len(wins) / len(rs):5.1f}%  avg {statistics.fmean(rs):+6.2f}R  "
            f"total {sum(rs):+7.1f}R  PF {pf}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trades")
    ap.add_argument("--split", required=True, help="first date of the test period, YYYY-MM-DD")
    ap.add_argument("--min-trades", type=int, default=10)
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.trades, newline="")))
    sel, test, full = defaultdict(list), defaultdict(list), defaultdict(list)
    by_year = defaultdict(lambda: defaultdict(list))
    for r in rows:
        x = float(r["r_multiple"])
        sym, day = r["symbol"], r["entry_time"][:10]
        full[sym].append(x)
        by_year[sym][day[:4]].append(x)
        (sel if day < args.split else test)[sym].append(x)

    all_test = [x for v in test.values() for x in v]
    print(f"Trades: {len(rows)} on {len(full)} stocks | selection < {args.split} <= test")
    print(f"All stocks, test period: {stats(all_test)}\n")

    eligible = {s: v for s, v in sel.items() if len(v) >= args.min_trades}
    picks = sorted(eligible, key=lambda s: -sum(eligible[s]))[:args.top]
    print(f"TOP {args.top} CHOSEN ON THE SELECTION PERIOD (min {args.min_trades} trades), then tested:")
    for s in picks:
        print(f"  {s:<6} selection: {stats(sel[s])}")
        print(f"  {'':<6} test:      {stats(test.get(s, []))}")
    print(f"  Combined test period of the {args.top} picks: {stats([x for s in picks for x in test.get(s, [])])}\n")

    years = sorted({y for v in by_year.values() for y in v})
    full_ok = {s: v for s, v in full.items() if len(v) >= args.min_trades}
    best = sorted(full_ok, key=lambda s: -sum(full_ok[s]))[:args.top]
    print(f"TOP {args.top} OVER THE WHOLE PERIOD (min {args.min_trades} trades; chosen with hindsight):")
    for s in best:
        per_year = "  ".join(f"{y}: {sum(by_year[s][y]):+6.1f}R/{len(by_year[s][y])}" for y in years)
        print(f"  {s:<6} {stats(full[s])}\n  {'':<6} {per_year}")

    counts = [len(v) for v in full_ok.values()]
    pool = [x for v in full_ok.values() for x in v]
    rng = random.Random(42)
    sims = []
    for _ in range(1000):
        rng.shuffle(pool)
        i, totals = 0, []
        for c in counts:
            totals.append(sum(pool[i:i + c]))
            i += c
        sims.append(sorted(totals, reverse=True)[:args.top])
    actual = [sum(full_ok[s]) for s in best]
    luck = [statistics.median(sim[k] for sim in sims) for k in range(args.top)]
    print("\nLuck benchmark (trade results shuffled across stocks, 1000 runs):")
    print("  rank:         " + "  ".join(f"#{k + 1:<7}" for k in range(args.top)))
    print("  actual top:   " + "  ".join(f"{a:+7.1f}R" for a in actual))
    print("  luck median:  " + "  ".join(f"{m:+7.1f}R" for m in luck))


if __name__ == "__main__":
    main()
