#!/usr/bin/env python3
"""Round 4: apply SHORTLIST_4.md's selection rule to the dev grid, and summarise any grid CSV.

  python3 backtest/select4.py pick --dev backtest/grid4_dev.csv --out backtest/finalists_round4.json
  python3 backtest/select4.py table --csv backtest/grid4_holdout_finalists.csv --keys backtest/finalists_round4.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lab4  # noqa: E402

NUM = ("n", "wins", "tgts", "stops", "sum_r", "sum_r2", "gross_win", "gross_loss")
REFERENCE = 'QQQ|nb3|["none", "first"]|0.3|1|3.0'


def read(path: str) -> list[dict]:
    rows = []
    for r in csv.DictReader(open(path)):
        for k in NUM:
            r[k] = float(r[k])
        r["n"] = int(r["n"])
        r["by_year"] = {int(y): v for y, v in json.loads(r["by_year"]).items()}
        rows.append(r)
    return rows


def with_pooled(rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for r in rows:
        groups[(r["family"], r["param"], r["stop"], r["max_trades"], r["rr"])].append(r)
    out = list(rows)
    for (fam, param, stop, mt, rr), g in groups.items():
        p = {"key": f"ALL|{fam}|{param}|{stop}|{mt}|{rr}", "ticker": "ALL", "family": fam, "param": param,
             "stop": stop, "max_trades": mt, "rr": rr, "instruments": len(g)}
        for k in NUM:
            p[k] = sum(x[k] for x in g)
        p["n"] = int(p["n"])
        by = defaultdict(float)
        for x in g:
            for y, v in x["by_year"].items():
                by[y] += v
        p["by_year"] = dict(by)
        out.append(p)
    return out


def stats(r: dict) -> dict:
    return lab4.describe({"n": r["n"], "wins": int(r["wins"]), "tgts": int(r["tgts"]), "sum_r": r["sum_r"],
                          "sum_r2": r["sum_r2"], "gross_win": r["gross_win"], "gross_loss": r["gross_loss"]})


def eligible(r: dict) -> bool:
    s = stats(r)
    min_n = 300 if r["ticker"] == "ALL" else 60
    return (s["n"] >= min_n and s["avg_r"] > 0 and r["by_year"].get(2023, 0) > 0
            and r["by_year"].get(2024, 0) > 0)


def top(rows, score, k=8, per_family=2, taken=()):
    picked, fam_count = [], defaultdict(int)
    for r in sorted(rows, key=score, reverse=True):
        if r["key"] in taken or fam_count[r["family"]] >= per_family:
            continue
        picked.append(r)
        fam_count[r["family"]] += 1
        if len(picked) == k:
            break
    return picked


def fmt(r: dict) -> str:
    s = stats(r)
    yrs = " ".join(f"{y}:{v:+.1f}" for y, v in sorted(r["by_year"].items()))
    return (f"| {r['ticker']} | {r['family']} {r['param']} | {r['stop']} | {r['max_trades']} | {s['n']} | "
            f"{100 * s['win']:.1f}% ({100 * s['win_lo']:.0f}-{100 * s['win_hi']:.0f}) | {100 * s['tgt']:.1f}% | "
            f"{s['avg_r']:+.3f} | {s['t']:.2f} | {s['pf']:.2f} | {yrs} |")


HEADER = ("| Instrument | Setting | Stop | Trades/day | n | Win rate (95% CI) | 3R target hit | Avg R | t | PF | R by year |\n"
          "|---|---|---|---|---|---|---|---|---|---|---|")


def pick(args) -> None:
    rows = with_pooled(read(args.dev))
    rr3 = [r for r in rows if float(r["rr"]) == 3.0]
    el = [r for r in rr3 if eligible(r)]
    tracks, taken = {}, set()
    for name, score in (("A_win_lb", lambda r: stats(r)["win_lo"]), ("B_target_lb", lambda r: stats(r)["tgt_lo"]),
                        ("C_t_stat", lambda r: stats(r)["t"])):
        tracks[name] = top(el, score, taken=taken)
        taken |= {r["key"] for r in tracks[name]}
    tracks["P_pooled"] = top([r for r in el if r["ticker"] == "ALL"], lambda r: stats(r)["t"], k=3, taken=taken)
    taken |= {r["key"] for r in tracks["P_pooled"]}
    keys = sorted(taken | {REFERENCE})
    json.dump(keys, open(args.out, "w"), indent=1)
    lines = [f"Dev rows at 1:3: {len(rr3)} ({sum(r['ticker'] != 'ALL' for r in rr3)} single-instrument + "
             f"{sum(r['ticker'] == 'ALL' for r in rr3)} pooled); eligible: {len(el)}", ""]
    for name, rs in tracks.items():
        lines += [f"### Track {name}", "", HEADER] + [fmt(r) for r in rs] + [""]
    best = {}
    for r in rr3:
        if r["n"] >= (300 if r["ticker"] == "ALL" else 60):
            s = stats(r)
            b = best.get(r["family"])
            if b is None or s["win"] > stats(b)["win"]:
                best[r["family"]] = r
    lines += ["### Highest dev win rate per family at 1:3 (n >= 60, eligibility not required)", "", HEADER]
    lines += [fmt(r) for r in sorted(best.values(), key=lambda r: -stats(r)["win"])] + [""]
    tg = max((r for r in rr3 if r["n"] >= 60), key=lambda r: stats(r)["tgt"])
    lines += [f"Highest dev 3R target-hit rate with n >= 60: {fmt(tg)}", ""]
    Path(args.summary).write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"{len(keys)} finalist keys -> {args.out}")


def table(args) -> None:
    rows = with_pooled(read(args.csv))
    keys = json.load(open(args.keys))
    by_key = {r["key"]: r for r in rows}
    lines = [HEADER]
    for k in keys:
        r = by_key.get(k)
        lines.append(fmt(r) if r else f"| {k} | (no trades) |")
    out = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(out + "\n")
    print(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("pick")
    a.add_argument("--dev", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--summary", default="backtest/results_round4/dev_selection.md")
    b = sub.add_parser("table")
    b.add_argument("--csv", required=True)
    b.add_argument("--keys", required=True)
    b.add_argument("--out")
    args = ap.parse_args()
    {"pick": pick, "table": table}[args.cmd](args)


if __name__ == "__main__":
    main()
