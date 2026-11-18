#!/usr/bin/env python3
"""Round 9 driver (SHORTLIST_9.md).

  python3 backtest/run_round9.py --inst <10-year cache> design
  python3 backtest/run_round9.py --inst <10-year cache> check
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import intraday_lab as il  # noqa: E402
import lab6  # noqa: E402
import lab8  # noqa: E402
import lab9  # noqa: E402

OUT = HERE / "results_round9"
DESIGN, CHECK = (20160101, 20221231), (20230101, 20260331)
TICKERS = ("GLD", "QQQ")


def load(inst):
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    return {tk: il.load_instrument(inst, tk) for tk in TICKERS}


def daily(d, t):
    return dict(zip(d["dkey"].tolist(), lab8.daily_r(d, t).tolist()))


def stats(d, t, span):
    dk = d["dkey"]
    dr = lab8.daily_r(d, t)
    m = (dk >= span[0]) & (dk <= span[1])
    x = dr[m]
    td = dk[t["day"].astype(int)] if len(t["r"]) else np.array([], int)
    tm = (td >= span[0]) & (td <= span[1])
    yrs = dk[m] // 10000
    by = {int(y): round(float(x[yrs == y].sum()), 2) for y in np.unique(yrs)}
    return {"sharpe": float(x.mean() / x.std() * np.sqrt(252)) if x.std() > 0 else 0.0, "trades": int(tm.sum()),
            "mean_r": float(t["r"][tm].mean()) if tm.any() else float("nan"),
            "win": float((t["r"][tm] > 0).mean()) if tm.any() else float("nan"),
            "years_positive": int(sum(v > 0 for v in by.values())), "years": len(by), "by_year": by}


def key(tk, cfg):
    return tk + " " + json.dumps(cfg, sort_keys=True)


def nb3_steady(data):
    d = data["QQQ"]
    t = lab8.costed(d, lab8.bracket8(d, lab6.nb3_signals(d, 2), rr=1.5, stop_atr=0.3, max_trades=2))
    return daily(d, t)


def design(inst):
    OUT.mkdir(exist_ok=True)
    data = load(inst)
    rows = {}
    for tk in TICKERS:
        for cfg in lab9.configs():
            rows[key(tk, cfg)] = {"ticker": tk, "cfg": cfg, "design": stats(data[tk], lab9.run(data[tk], tk, cfg), DESIGN)}
    el = [k for k, r in rows.items() if r["design"]["trades"] >= 200 and r["design"]["years_positive"] >= 5
          and r["design"]["sharpe"] > 0]
    el.sort(key=lambda k: -rows[k]["design"]["sharpe"])
    picks = {f"P{i + 1}": k for i, k in enumerate(el[:3])}
    if not any(rows[k]["ticker"] == "GLD" for k in picks.values()):
        g = [k for k in el if rows[k]["ticker"] == "GLD"]
        if g:
            picks["PG"] = g[0]
    (OUT / "design.json").write_text(json.dumps({"rows": rows, "eligible": el, "picks": picks}, indent=1))
    for tk in TICKERS:
        rs = sorted((r for r in rows.values() if r["ticker"] == tk), key=lambda r: -r["design"]["sharpe"])
        pos = sum(1 for r in rs if r["design"]["sharpe"] > 0)
        print(f"== {tk}: {pos} of {len(rs)} settings with a positive design Sharpe; best 6:")
        for r in rs[:6]:
            s = r["design"]
            print(f"   Sharpe {s['sharpe']:+.2f} trades {s['trades']:5d} R {s['mean_r']:+.3f} win {100 * s['win']:.0f}% "
                  f"yrs+ {s['years_positive']}/{s['years']}  {r['cfg']}")
        by = {}
        for r in rs:
            by.setdefault(r["cfg"]["family"], []).append(r["design"]["sharpe"])
        print("   best Sharpe by family:", {f: round(max(v), 2) for f, v in by.items()})
    print("eligible:", len(el), "picks:", picks)


def check(inst):
    data = load(inst)
    des = json.loads((OUT / "design.json").read_text())
    base = nb3_steady(data)
    out = {}
    for p, k in des["picks"].items():
        r = des["rows"][k]
        tk, cfg = r["ticker"], r["cfg"]
        t = lab9.run(data[tk], tk, cfg)
        s = stats(data[tk], t, CHECK)
        dd = daily(data[tk], t)
        days = sorted(x for x in set(dd) & set(base) if CHECK[0] <= x <= CHECK[1])
        a, b = np.array([dd[x] for x in days]), np.array([base[x] for x in days])
        comb = a + b
        s.update({"corr_with_nb3_steady": float(np.corrcoef(a, b)[0, 1]),
                  "nb3_steady_sharpe_same_days": float(b.mean() / b.std() * np.sqrt(252)),
                  "combined_sharpe": float(comb.mean() / comb.std() * np.sqrt(252)),
                  "works": bool(s["sharpe"] > 0.5 and s["mean_r"] > 0), "beats_nb3_steady": bool(s["sharpe"] > 1.57)})
        out[p] = {"key": k, "design": r["design"], "check": s}
        print(f"{p} {k}\n   design Sharpe {r['design']['sharpe']:+.2f} -> check Sharpe {s['sharpe']:+.2f}, R {s['mean_r']:+.3f}, "
              f"trades {s['trades']}, yrs+ {s['years_positive']}/{s['years']} | works {s['works']} | corr with NB3 steady "
              f"{s['corr_with_nb3_steady']:+.2f}, combined Sharpe {s['combined_sharpe']:.2f} vs NB3 steady {s['nb3_steady_sharpe_same_days']:.2f}")
    (OUT / "check.json").write_text(json.dumps(out, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", required=True)
    ap.add_argument("stage", choices=("design", "check"))
    a = ap.parse_args()
    design(a.inst) if a.stage == "design" else check(a.inst)


if __name__ == "__main__":
    main()
