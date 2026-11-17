#!/usr/bin/env python3
"""Round 6 driver (SHORTLIST_6.md): aggressive NB3 management for fast Lucid Flex payouts.

  python3 backtest/run_lucid6.py --inst <10-year cache> design
  python3 backtest/run_lucid6.py --inst <10-year cache> check
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import warnings
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import intraday_lab as il  # noqa: E402
import lab4  # noqa: E402
import lab6  # noqa: E402
import lucid5 as lc  # noqa: E402
import prop_sim as ps  # noqa: E402
import run_lucid5 as rl  # noqa: E402

OUT = HERE / "results_round6"
ENTRIES = (("market", 0.0), ("limit", 0.05), ("limit", 0.10), ("limit", 0.20))
STOPS = (0.05, 0.075, 0.10, 0.15, 0.20, 0.30, "bar")
BES = (0.0, 1.0)
RRS = (1.0, 1.5, 2.0, 3.0)
MTS = (1, 2)
EVAL_SIZES = [("budget", x) for x in (350.0, 500.0, 700.0, 1000.0)] + [("cush", f) for f in (0.2, 0.3, 0.5)]
FUND_SIZES = [("budget", x) for x in (250.0, 350.0, 500.0)] + [("cush", 0.25)]
KEEPS = (0.0, 500.0)
N_DESIGN, N_CHECK, H, ACCOUNTS, SEED = 1000, 2000, 252, 5, 6262
SNAPS = (21, 63, 126, 252)


@dataclass(frozen=True)
class Variant:
    entry: str = "market"
    offset: float = 0.0
    stop: object = 0.3
    be: float = 0.0
    rr: float = 1.5
    mt: int = 2


BASELINES = {
    "round5_lucid_optimized": (Variant("market", 0.0, 0.3, 0.0, 1.5, 2), ("budget", 350.0), ("budget", 350.0), 500.0),
    "current_bot": (Variant("market", 0.0, 0.3, 0.0, 3.0, 1), ("budget", 350.0), ("budget", 250.0), 2000.0),
}
_D: dict = {}


def pool6(d: dict, span, v: Variant, slip_ticks: float = 1.0) -> dict:
    """Day pool of the variant's MNQ trades, dollar risk rescaled to today's volatility (round 5, Part 2b)."""
    dd = lab4.subset(d, *span)
    sig = lab6.nb3_signals(dd, v.mt)
    t = lab6.bracket6(dd, sig, v.rr, v.stop, entry=v.entry, offset=v.offset, be=v.be, max_trades=v.mt,
                      slip=slip_ticks * ps.MNQ_TICK_Q, commission=0.0, tick=ps.MNQ_TICK_Q)
    pool = lc.pool_from_trades(dd, t)
    key = ("scale",) + tuple(span)
    if key not in _D:
        ref = lc.build_pool(d, *span, 0.3, 3.0, 1)
        _D[key] = rl.NOW_ONE_MNQ / float(np.median(ref["dpr1"][ref["has1"]]))
    for j in (1, 2):
        pool[f"dpr{j}"] = pool[f"dpr{j}"] * _D[key]
    pool["trades"] = len(t["r"])
    pool["mean_r"] = float(t["r"].mean()) if len(t["r"]) else float("nan")
    pool["target_share"] = float((t["kind"] == 1).mean()) if len(t["r"]) else float("nan")
    return pool


def run_one(pool, st, v, es, fs, keep) -> dict:
    cfg = lc.Config(0.0, v.rr, v.mt, es, fs, keep)
    res = lc.simulate(pool, st, cfg, max_accounts=ACCOUNTS, scaling_plan=True, snapshots=SNAPS)
    fp = res["first_pay"]
    c6, c12 = res["snap"][126], res["snap"][252]
    out = {f"pay_{m}m": float(((fp >= 0) & (fp < 21 * m)).mean()) for m in (1, 3, 6, 12)}
    out.update({"cash_6m_mean": float(c6.mean()), "cash_6m_median": float(np.median(c6)),
                "cash_12m_mean": float(c12.mean()), "cash_12m_median": float(np.median(c12)),
                "p_ahead_6m": float((c6 > 0).mean()), "p_ahead_12m": float((c12 > 0).mean()),
                "accounts_used": float(res["accounts"].mean()),
                "first_pay_days_median": float(np.median(fp[fp >= 0] + 1)) if (fp >= 0).any() else float("nan")})
    return out


def vrow(v: Variant, es, fs, keep) -> dict:
    return {"entry": v.entry, "offset": v.offset, "stop": v.stop, "be": v.be, "rr": v.rr, "mt": v.mt,
            "eval_size": f"{es[0]}:{es[1]}", "funded_size": f"{fs[0]}:{fs[1]}", "keep": keep}


def parse(r: dict):
    sz = lambda x: (x.split(":")[0], float(x.split(":")[1]))  # noqa: E731
    stop = r["stop"] if r["stop"] == "bar" else float(r["stop"])
    v = Variant(r["entry"], float(r["offset"]), stop, float(r["be"]), float(r["rr"]), int(r["mt"]))
    return v, sz(r["eval_size"]), sz(r["funded_size"]), float(r["keep"])


def _init(inst):
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    _D["d"] = il.load_instrument(inst, "QQQ")


def design_job(v: Variant):
    pool = pool6(_D["d"], rl.DESIGN, v)
    st = lc.streams(pool, N_DESIGN, H, rl.BLOCK, SEED)
    info = {"trades": pool["trades"], "mean_r": pool["mean_r"], "target_share": pool["target_share"]}
    rows = []
    for es in EVAL_SIZES:
        for fs in FUND_SIZES:
            for keep in KEEPS:
                rows.append({**vrow(v, es, fs, keep), **info, **run_one(pool, st, v, es, fs, keep)})
    return rows


def variants():
    return [Variant(e, o, s, b, r, m) for e, o in ENTRIES for s in STOPS for b in BES for r in RRS for m in MTS]


def design(inst: str) -> None:
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    rows = []
    vs = variants()
    with Pool(4, initializer=_init, initargs=(inst,)) as p:
        for i, part in enumerate(p.imap_unordered(design_job, vs, chunksize=2)):
            rows += part
            if (i + 1) % 16 == 0:
                print(f"variants {i + 1}/{len(vs)} ({time.time() - t0:.0f}s)", flush=True)
    with open(OUT / "design_grid.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    ok = [r for r in rows if r["cash_12m_mean"] > 0]
    a = max(ok, key=lambda r: (r["pay_3m"], r["cash_12m_mean"]))
    b = max(rows, key=lambda r: r["cash_6m_mean"])
    c = max([r for r in ok if r["pay_3m"] >= a["pay_3m"] - 0.03], key=lambda r: r["cash_12m_mean"])
    picks = {"A_fastest_payout": a, "B_most_cash_6m": b, "C_balanced": c}
    _D["d"] = il.load_instrument(inst, "QQQ")
    for name, (v, es, fs, keep) in BASELINES.items():
        pool = pool6(_D["d"], rl.DESIGN, v)
        st = lc.streams(pool, N_DESIGN, H, rl.BLOCK, SEED)
        picks[name] = {**vrow(v, es, fs, keep), "trades": pool["trades"], "mean_r": pool["mean_r"],
                       "target_share": pool["target_share"], **run_one(pool, st, v, es, fs, keep)}
    (OUT / "picks.json").write_text(json.dumps(picks, indent=1, default=str))
    print(f"{len(rows)} settings, {len(ok)} with positive 12-month cash ({time.time() - t0:.0f}s)")
    for k, r in picks.items():
        print(k, json.dumps(r, default=str))


def check(inst: str) -> None:
    _init(inst)
    d = _D["d"]
    picks = json.loads((OUT / "picks.json").read_text())
    cases = [("check 2023-26, full edge", rl.CHECK, 1.0), ("check 2023-26, half edge", rl.CHECK, 0.5),
             ("design 2016-22, half edge", rl.DESIGN, 0.5), ("design 2016-22, no edge (extra)", rl.DESIGN, 0.0)]
    out = {}
    for name, r in picks.items():
        v, es, fs, keep = parse(r)
        out[name] = {"setting": vrow(v, es, fs, keep), "design": {k: r[k] for k in r if k not in vrow(v, es, fs, keep)}}
        for label, span, edge in cases:
            pool = pool6(d, span, v)
            st = lc.streams(pool, N_CHECK, H, rl.BLOCK, SEED + 1, edge_keep=edge)
            out[name][label] = {"trades": pool["trades"], "mean_r": pool["mean_r"], **run_one(pool, st, v, es, fs, keep)}
    (OUT / "check.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", required=True)
    ap.add_argument("stage", choices=("design", "check"))
    a = ap.parse_args()
    design(a.inst) if a.stage == "design" else check(a.inst)


if __name__ == "__main__":
    main()
