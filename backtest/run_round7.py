#!/usr/bin/env python3
"""Round 7 driver (SHORTLIST_7.md): improve NB3's edge on 10 years, single QQQ and an index-futures portfolio.

  python3 backtest/run_round7.py --inst <10-year cache> design     # 128 rule sets on 2016-2022, picks
  python3 backtest/run_round7.py --inst <10-year cache> check      # picks + baselines once on 2023-2026
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import sys
import warnings
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import intraday_lab as il  # noqa: E402
import lab7  # noqa: E402

OUT = HERE / "results_round7"
TICKERS = ("QQQ", "SPY", "IWM", "DIA")
DESIGN = (20160101, 20221231)
CHECK = (20230101, 20260331)
EXITS = (("bracket", 0.3, 3.0), ("bracket", 0.1, 2.0), ("trail", 0.3), ("trail", 0.1))
NB3 = {"k": 1.0, "gap": False, "check30": False, "regime": False, "exit": ("bracket", 0.3, 3.0), "mt": 1}


def rules():
    for k, gap, c30, reg, ex, mt in itertools.product((1.0, 1.5), (False, True), (False, True), (False, True), EXITS, (1, 2)):
        yield {"k": k, "gap": gap, "check30": c30, "regime": reg, "exit": ex, "mt": mt}


def rkey(r):
    return json.dumps(r, sort_keys=True)


def load(inst):
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    data = {tk: lab7.add_regime(il.load_instrument(inst, tk)) for tk in TICKERS}
    days = np.unique(np.concatenate([d["dkey"] for d in data.values()]))
    return data, days


def daily(data, days, rule):
    """{ticker: daily R aligned to `days`} and trade-level arrays per ticker."""
    out, trades = {}, {}
    for tk, d in data.items():
        t = lab7.run(d, tk, rule)
        dr = np.zeros(len(days))
        pos = np.searchsorted(days, d["dkey"])
        np.add.at(dr, pos, lab7.daily_r(d, t))
        out[tk] = dr
        trades[tk] = (d["dkey"][t["day"].astype(int)] if len(t["r"]) else np.array([], int), t["r"])
    return out, trades


def stats(dr, days, span, trades=None):
    m = (days >= span[0]) & (days <= span[1])
    x = dr[m]
    yrs = days[m] // 10000
    s = {"mean_day_r": float(x.mean()), "sharpe": float(x.mean() / x.std() * np.sqrt(252)) if x.std() > 0 else 0.0,
         "t": float(x.mean() / x.std() * np.sqrt(len(x))) if x.std() > 0 else 0.0,
         "by_year": {int(y): round(float(x[yrs == y].sum()), 2) for y in np.unique(yrs)}}
    s["years_positive"] = int(sum(v > 0 for v in s["by_year"].values()))
    if trades is not None:
        dk, r = trades
        mm = (dk >= span[0]) & (dk <= span[1])
        s["trades"] = int(mm.sum())
        s["mean_trade_r"] = float(r[mm].mean()) if mm.any() else float("nan")
    return s


def evaluate(data, days, rule, span):
    per, trades = daily(data, days, rule)
    res = {tk: stats(per[tk], days, span, trades[tk]) for tk in TICKERS}
    res["PORTFOLIO"] = stats(sum(per.values()), days, span)
    return res


def design(inst):
    OUT.mkdir(exist_ok=True)
    data, days = load(inst)
    rows = []
    for rule in rules():
        res = evaluate(data, days, rule, DESIGN)
        rows.append({"rule": rkey(rule), **{f"{u}_{k}": res[u][k] for u in ("QQQ", "PORTFOLIO")
                                            for k in ("sharpe", "mean_day_r", "t", "years_positive")},
                     "QQQ_trades": res["QQQ"]["trades"], "QQQ_mean_trade_r": res["QQQ"]["mean_trade_r"]})
    with open(OUT / "design.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    pick_p = max((r for r in rows if r["PORTFOLIO_years_positive"] >= 5), key=lambda r: r["PORTFOLIO_sharpe"])
    pick_q = max((r for r in rows if r["QQQ_years_positive"] >= 5), key=lambda r: r["QQQ_sharpe"])
    base = next(r for r in rows if r["rule"] == rkey(NB3))
    picks = {"P_portfolio": pick_p, "Q_qqq": pick_q, "NB3_baseline": base}
    (OUT / "picks.json").write_text(json.dumps(picks, indent=1))
    for k, r in picks.items():
        print(k, json.dumps(r))
    top = sorted(rows, key=lambda r: -r["PORTFOLIO_sharpe"])[:10]
    print("top-10 portfolio Sharpe (design):")
    for r in top:
        print(f"  {r['PORTFOLIO_sharpe']:.2f} yrs+{r['PORTFOLIO_years_positive']} | QQQ {r['QQQ_sharpe']:.2f} | {r['rule']}")


def check(inst):
    data, days = load(inst)
    picks = json.loads((OUT / "picks.json").read_text())
    out = {}
    for name, r in picks.items():
        rule = json.loads(r["rule"])
        rule["exit"] = tuple(rule["exit"])
        out[name] = {"rule": rule, "design": evaluate(data, days, rule, DESIGN), "check": evaluate(data, days, rule, CHECK)}
    (OUT / "check.json").write_text(json.dumps(out, indent=1))
    for name, v in out.items():
        print(f"== {name}: {v['rule']}")
        for per in ("design", "check"):
            for u in ("QQQ", "SPY", "IWM", "DIA", "PORTFOLIO"):
                s = v[per][u]
                extra = f" trades {s['trades']} meanR {s['mean_trade_r']:+.3f}" if "trades" in s else ""
                print(f"   {per:6s} {u:9s} Sharpe {s['sharpe']:+.2f} t {s['t']:+.2f} R/day {s['mean_day_r']:+.3f} "
                      f"years+ {s['years_positive']}/{len(s['by_year'])}{extra}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", required=True)
    ap.add_argument("stage", choices=("design", "check"))
    a = ap.parse_args()
    design(a.inst) if a.stage == "design" else check(a.inst)


if __name__ == "__main__":
    main()
