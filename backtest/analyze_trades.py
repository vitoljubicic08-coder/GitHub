#!/usr/bin/env python3
"""Breakdowns of a SIP-ORB backtest trades.csv (output of sip_orb_backtest.py).

Usage:  python3 backtest/analyze_trades.py backtest/results/trades.csv
"""
from __future__ import annotations

import csv
import random
import statistics
import sys
from collections import defaultdict


def load(path: str) -> list[dict]:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("r_multiple", "net_pnl", "gross_pnl", "planned_risk", "entry_price",
                  "signal_close", "entry_notional_pct", "commission", "stop_distance"):
            r[k] = float(r[k])
        r["gross_r"] = r["gross_pnl"] / r["planned_risk"]
    return rows


def line(label: str, rows: list[dict]) -> str:
    if not rows:
        return f"{label:<22} {0:>6}"
    r = [x["r_multiple"] for x in rows]
    wins = sum(x["net_pnl"] > 0 for x in rows)
    pos = sum(x["net_pnl"] for x in rows if x["net_pnl"] > 0)
    neg = -sum(x["net_pnl"] for x in rows if x["net_pnl"] <= 0)
    pf = f"{pos / neg:5.2f}" if neg > 0 else "  n/a"
    return (f"{label:<22} {len(rows):>6} {100 * wins / len(rows):>7.1f}% {statistics.fmean(r):>+8.3f} "
            f"{statistics.median(r):>+8.3f} {sum(r):>+9.1f} {pf:>6}")


def main(path: str) -> None:
    rows = sorted(load(path), key=lambda x: x["entry_time"])
    rng = random.Random(7)
    r = [x["r_multiple"] for x in rows]
    n = len(rows)

    print(f"{'group':<22} {'trades':>6} {'win':>8} {'avg R':>8} {'med R':>8} {'sum R':>9} {'PF':>6}")
    print(line("ALL", rows))
    print(line("LONG", [x for x in rows if x["side"] == "LONG"]))
    print(line("SHORT", [x for x in rows if x["side"] == "SHORT"]))
    by_month = defaultdict(list)
    for x in rows:
        by_month[x["entry_time"][:7]].append(x)
    for m in sorted(by_month):
        print(line(f"month {m}", by_month[m]))
    for lo, hi in ((5, 20), (20, 50), (50, 150), (150, 1e9)):
        label = f"price {lo}-{int(hi)}" if hi < 1e9 else f"price {lo}+"
        print(line(label, [x for x in rows if lo <= x["signal_close"] < hi]))
    reason = defaultdict(list)
    for x in rows:
        reason[x["exit_reason"]].append(x)
    for k in sorted(reason):
        print(line(f"exit {k}", reason[k]))
    capped = [x for x in rows if x["entry_notional_pct"] >= 95.0]
    print(line("size: notional cap", capped))
    print(line("size: risk budget", [x for x in rows if x["entry_notional_pct"] < 95.0]))

    print("\nR distribution (net):")
    edges = [(-99, -1.5), (-1.5, -1.0), (-1.0, 0.0), (0.0, 1.0), (1.0, 2.0), (2.0, 5.0), (5.0, 99)]
    for lo, hi in edges:
        k = sum(lo <= v < hi for v in r)
        print(f"  [{lo:>5}, {hi:>3}) {k:>6}  {100 * k / n:5.1f}%")

    print(f"\nCost drag: avg gross R {statistics.fmean(x['gross_r'] for x in rows):+.3f}  "
          f"-> avg net R {statistics.fmean(r):+.3f}")
    srt = sorted(r, reverse=True)
    top = max(1, n // 20)
    print(f"Top 5% of trades ({top}) contribute {sum(srt[:top]):+.1f} R of {sum(r):+.1f} R total; "
          f"without them avg R = {statistics.fmean(srt[top:]):+.3f}")

    means = sorted(statistics.fmean(rng.choices(r, k=n)) for _ in range(5000))
    print(f"Bootstrap 95% CI of avg net R: [{means[124]:+.3f}, {means[4874]:+.3f}]  "
          f"(P(avg R <= 0) = {sum(m <= 0 for m in means) / len(means):.3f})")

    first = rows[:1000]
    if n > 1000:
        print("\nFirst 1000 trades chronologically:")
        print(line("FIRST 1000", first))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "backtest/results/trades.csv")
