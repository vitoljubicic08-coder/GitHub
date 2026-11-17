#!/usr/bin/env python3
"""Export the verified NB3 V2 trade list from the ORIGINAL research code (backtest/nb3_trades.py).

This is the reference the bot is checked against. It uses the research implementation untouched:
nb3_trades.extract(d) with its default execution assumptions (2 ticks of $0.01 slippage, $0.005 per
share per side), on the same QQQ 1-minute cache, for sessions up to 2026-03-31 (675 trades).
Usage: python3 nb3bot/validation/export_reference.py <QQQ cache dir> [out.csv]
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backtest"))

import intraday_lab as il  # noqa: E402
import nb3_trades as nt  # noqa: E402

FIELDS = ("dkey", "direction", "signal_bar", "entry_min", "fill", "dist", "exit_min", "exit_px", "reason",
          "r_net", "r_gross")


def main() -> None:
    cache = sys.argv[1]
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).with_name("reference_nb3v2_qqq_trades.csv")
    d = il.load_instrument(cache, "QQQ")
    trades = [t for t in nt.extract(d) if t.dkey <= 20260331]
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for t in trades:
            w.writerow([t.dkey, t.direction, t.signal_bar, t.entry_min, repr(t.fill), repr(t.dist), t.exit_min,
                        repr(t.exit_px), t.reason, repr(t.r_net), repr(t.r_gross)])
    print(f"{len(trades)} reference trades -> {out}")


if __name__ == "__main__":
    main()
