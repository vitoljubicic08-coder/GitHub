#!/usr/bin/env python3
"""Round 8 driver (SHORTLIST_8.md).

  python3 backtest/run_round8.py --inst <10-year cache> --ext <round-8 outside data> design
  python3 backtest/run_round8.py --inst <10-year cache> --ext <round-8 outside data> check
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
import lab4  # noqa: E402
import lab6  # noqa: E402
import lab8  # noqa: E402
import lucid5 as lc  # noqa: E402
import run_lucid5 as rl  # noqa: E402

OUT = HERE / "results_round8"
DESIGN = (20160101, 20221231)
CHECK = (20230101, 20260331)
BASE = {"rr": 1.5, "mt": 2}
NB3V2 = {"rr": 3.0, "mt": 1}
VARIANTS = {"sd_target_k1": ("sd", 1.0), "sd_target_k2": ("sd", 2.0), "ote_705_ext27": ("ote", 0.705, 0.27),
            "ote_705_retest": ("ote", 0.705, 0.0), "ote_618_ext27": ("ote", 0.618, 0.27)}


def setup(inst, ext):
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    d = il.load_instrument(inst, "QQQ")
    F = {**lab8.day_features(d, lab8.load_external(ext)), **lab8.bar_features(d)}
    return d, F, lab8.filters(d, F)


def trades(d, base, filt=None, variant=None, keep=None, cost=True):
    sig = lab6.nb3_signals(d, base["mt"])
    if keep is not None:
        sig = lab8.apply_filter(sig, keep)
    kw = {}
    if variant is not None:
        v = VARIANTS[variant]
        if v[0] == "sd":
            kw["tgt_lvl"] = lab8.sd_targets(d, sig, v[1])
        else:
            kw["lim"], kw["stp_lvl"], kw["tgt_lvl"] = lab8.ote_levels(d, sig, v[1], v[2])
    t = lab8.bracket8(d, sig, rr=base["rr"], stop_atr=0.3, max_trades=base["mt"], **kw)
    return lab8.costed(d, t) if cost else t


def stats(d, t, span):
    dr = lab8.daily_r(d, t)
    dk = d["dkey"]
    m = (dk >= span[0]) & (dk <= span[1])
    x = dr[m]
    tm = (dk[t["day"].astype(int)] >= span[0]) & (dk[t["day"].astype(int)] <= span[1]) if len(t["r"]) else np.array([], bool)
    yrs = dk[m] // 10000
    by = {int(y): round(float(x[yrs == y].sum()), 2) for y in np.unique(yrs)}
    return {"sharpe": float(x.mean() / x.std() * np.sqrt(252)) if x.std() > 0 else 0.0, "mean_day_r": float(x.mean()),
            "trades": int(tm.sum()), "mean_trade_r": float(t["r"][tm].mean()) if tm.any() else float("nan"),
            "years_positive": int(sum(v > 0 for v in by.values())), "years": len(by), "by_year": by}


def evaluate(d, keepsets, span):
    rows = {}
    for name, keep in keepsets.items():
        rows[name] = {"base": stats(d, trades(d, BASE, keep=keep), span),
                      "nb3v2": stats(d, trades(d, NB3V2, keep=keep), span)}
    return rows


def design(inst, ext):
    OUT.mkdir(exist_ok=True)
    d, F, filt = setup(inst, ext)
    base = {"base": stats(d, trades(d, BASE), DESIGN), "nb3v2": stats(d, trades(d, NB3V2), DESIGN)}
    rows = {"filter:" + k: v for k, v in evaluate(d, filt, DESIGN).items()}
    for v in VARIANTS:
        rows["variant:" + v] = {"base": stats(d, trades(d, BASE, variant=v), DESIGN),
                                "nb3v2": stats(d, trades(d, NB3V2, variant=v), DESIGN)}
    b = base["base"]["sharpe"]
    elig = {k: r for k, r in rows.items() if r["base"]["trades"] >= 300 and r["base"]["years_positive"] >= 5
            and r["base"]["sharpe"] > b}
    fil = sorted((k for k in elig if k.startswith("filter:")), key=lambda k: -elig[k]["base"]["sharpe"])
    var = sorted((k for k in elig if k.startswith("variant:")), key=lambda k: -elig[k]["base"]["sharpe"])
    picks = {f"P{i + 1}": k for i, k in enumerate(fil[:3])}
    if len(fil) >= 2:
        picks["P4"] = f"combo:{fil[0]}&{fil[1]}"
    if var:
        picks["P5"] = var[0]
    if "P4" in picks:
        k1, k2 = fil[0].split(":")[1], fil[1].split(":")[1]
        keep = (filt[k1][0] & filt[k2][0], filt[k1][1] & filt[k2][1])
        rows[picks["P4"]] = {"base": stats(d, trades(d, BASE, keep=keep), DESIGN), "nb3v2": stats(d, trades(d, NB3V2, keep=keep), DESIGN)}
    out = {"base": base, "rows": rows, "eligible": sorted(elig), "picks": picks}
    (OUT / "design.json").write_text(json.dumps(out, indent=1))
    print(f"BASE design: Sharpe {b:.2f}, trades {base['base']['trades']}, R/trade {base['base']['mean_trade_r']:+.3f} | "
          f"NB3 V2 Sharpe {base['nb3v2']['sharpe']:.2f}")
    for k, r in sorted(rows.items(), key=lambda kv: -kv[1]["base"]["sharpe"]):
        s = r["base"]
        print(f"  {k:36s} Sharpe {s['sharpe']:+.2f} trades {s['trades']:5d} R/trade {s['mean_trade_r']:+.3f} "
              f"yrs+ {s['years_positive']}/{s['years']} | NB3V2 Sharpe {r['nb3v2']['sharpe']:+.2f}" + ("  <-- eligible" if k in elig else ""))
    print("picks:", picks)


def keep_for(name, filt):
    if name.startswith("filter:"):
        return filt[name.split(":")[1]], None
    if name.startswith("combo:"):
        k1, k2 = (x.split(":")[1] for x in name.split(":", 1)[1].split("&"))
        return (filt[k1][0] & filt[k2][0], filt[k1][1] & filt[k2][1]), None
    return None, name.split(":")[1]


def lucid(d, keep, variant, span):
    """One $130 LucidFlex account at today's volatility (round 6 model), 2,000 runs, 12 months."""
    dd = lab4.subset(d, *span)
    sig = lab6.nb3_signals(dd, 2)
    if keep is not None:
        m = (d["dkey"] >= span[0]) & (d["dkey"] <= span[1])
        sig = lab8.apply_filter(sig, (keep[0][m], keep[1][m]))
    kw = {}
    if variant is not None:
        v = VARIANTS[variant]
        if v[0] == "sd":
            kw["tgt_lvl"] = lab8.sd_targets(dd, sig, v[1])
        else:
            kw["lim"], kw["stp_lvl"], kw["tgt_lvl"] = lab8.ote_levels(dd, sig, v[1], v[2])
    t = lab8.bracket8(dd, sig, rr=1.5, stop_atr=0.3, max_trades=2, **kw)
    pool = lc.pool_from_trades(dd, t)
    ref = lc.build_pool(d, *span, 0.3, 3.0, 1)
    scale = rl.NOW_ONE_MNQ / float(np.median(ref["dpr1"][ref["has1"]]))
    for j in (1, 2):
        pool[f"dpr{j}"] = pool[f"dpr{j}"] * scale
    st = lc.streams(pool, 2000, 252, 10, 8888)
    cfg = lc.Config(0.0, 1.5, 2, ("budget", 350.0), ("budget", 350.0), 500.0)
    m = lc.metrics(lc.simulate(pool, st, cfg, scaling_plan=True))
    return {k: m[k] for k in ("pass", "payout_6m", "payout_12m", "net_mean", "days_to_first_payout_med")}


def check(inst, ext):
    d, F, filt = setup(inst, ext)
    des = json.loads((OUT / "design.json").read_text())
    picks = des["picks"]
    base_c = {"base": stats(d, trades(d, BASE), CHECK), "nb3v2": stats(d, trades(d, NB3V2), CHECK)}
    out = {"base": {"design": des["base"], "check": base_c,
                    "lucid_2023_26": lucid(d, None, None, CHECK), "lucid_2016_22": lucid(d, None, None, DESIGN)}, "picks": {}}
    print(f"BASE check: Sharpe {base_c['base']['sharpe']:.2f}, R/trade {base_c['base']['mean_trade_r']:+.3f}, trades {base_c['base']['trades']}")
    for p, name in picks.items():
        keep, variant = keep_for(name, filt)
        res = {"base": stats(d, trades(d, BASE, keep=keep, variant=variant), CHECK),
               "nb3v2": stats(d, trades(d, NB3V2, keep=keep, variant=variant), CHECK)}
        improved = res["base"]["sharpe"] > base_c["base"]["sharpe"]
        entry = {"name": name, "design": des["rows"][name], "check": res, "improved": improved}
        if improved:
            entry["lucid_2023_26"] = lucid(d, keep, variant, CHECK)
            entry["lucid_2016_22"] = lucid(d, keep, variant, DESIGN)
        out["picks"][p] = entry
        s = res["base"]
        print(f"{p} {name:40s} check Sharpe {s['sharpe']:+.2f} (design {des['rows'][name]['base']['sharpe']:+.2f}) "
              f"R/trade {s['mean_trade_r']:+.3f} trades {s['trades']} -> {'IMPROVED' if improved else 'not improved'} "
              f"| NB3V2 check {res['nb3v2']['sharpe']:+.2f} vs {base_c['nb3v2']['sharpe']:+.2f}")
    print("Lucid base:", out["base"]["lucid_2023_26"], out["base"]["lucid_2016_22"])
    for p, e in out["picks"].items():
        if e["improved"]:
            print("Lucid", p, e["lucid_2023_26"], e["lucid_2016_22"])
    # information only: QQQ overnight drift (not tradable on LucidFlex)
    on = lab8.overnight_returns(d)
    info = {}
    for name, span in (("2016-22", DESIGN), ("2023-26", CHECK)):
        m = (d["dkey"] >= span[0]) & (d["dkey"] <= span[1]) & ~np.isnan(on)
        x = on[m]
        info[name] = {"mean_bp": float(x.mean() * 1e4), "sharpe": float(x.mean() / x.std() * np.sqrt(252)), "days": int(m.sum())}
    out["overnight_info"] = info
    print("QQQ close-to-open drift (information only):", info)
    (OUT / "check.json").write_text(json.dumps(out, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", required=True)
    ap.add_argument("--ext", required=True)
    ap.add_argument("stage", choices=("design", "check"))
    a = ap.parse_args()
    design(a.inst, a.ext) if a.stage == "design" else check(a.inst, a.ext)


if __name__ == "__main__":
    main()
