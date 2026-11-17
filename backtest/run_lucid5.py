#!/usr/bin/env python3
"""Round 5 driver (SHORTLIST_5.md).

  python3 backtest/run_lucid5.py --inst <10-year cache> nb3      # Part 1: NB3 V2 on 2016-2026, by year
  python3 backtest/run_lucid5.py --inst <10-year cache> design   # Part 2: grid on 2016-2022 and the picks
  python3 backtest/run_lucid5.py --inst <10-year cache> check    # Part 2: the picks once on 2023-2026
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import warnings
from dataclasses import asdict
from multiprocessing import Pool
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import intraday_lab as il  # noqa: E402
import lab4  # noqa: E402
import lucid5 as lc  # noqa: E402
import prop_sim as ps  # noqa: E402

OUT = HERE / "results_round5"
NEW = (20160101, 20230228)
DESIGN = (20160101, 20221231)
CHECK = (20230101, 20260331)
EXITS = [(s, rr, mt) for s in (0.2, 0.3, 0.4) for rr in (1.0, 1.5, 2.0, 3.0) for mt in (1, 2)]
EVAL_SIZES = [("budget", float(x)) for x in (250, 350, 500, 700)] + [("cush", f) for f in (0.10, 0.15, 0.20, 0.30)]
FUND_SIZES = [("budget", float(x)) for x in (150, 250, 350, 500)] + [("cush", f) for f in (0.10, 0.15, 0.20)]
KEEPS = (0.0, 500.0, 1000.0, 2000.0)
N, H, BLOCK, SEED = 2000, 252, 10, 20261117
BASELINE = lc.Config(0.3, 3.0, 1, ("budget", 350.0), ("budget", 250.0), 2000.0)
_D: dict = {}


def load(inst: str) -> dict:
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    return il.load_instrument(inst, "QQQ")


# ----------------------------------------------------------------------------- Part 1
def part1(d: dict) -> None:
    sig, _ = lab4.signals4(d, "nb3", ("none", "first"))
    rows = []
    for label, kw in (("research costs (2 x $0.01 + $0.005/share)", {}),
                      ("MNQ costs (1 tick, $1.50 per round turn charged on 1 contract)", {"slip": ps.MNQ_TICK_Q, "commission": 0.0})):
        t = lab4.bracket(d, sig, 0.3, rrs=(3.0,), **kw)[3.0]
        dk = d["dkey"][t["day"].astype(int)]
        r = t["r"].copy()
        if "commission" in kw:                          # $1.50 per MNQ round turn in R units
            r = r - lc.COMM / (t["dist"] * d["atr_prev"][t["day"].astype(int)] * lc.DPR_PER_QQQ)
        spans = [(str(y), y * 10000, y * 10000 + 9999) for y in range(2016, 2027)]
        spans += [("NEW 2016-01..2023-02", *NEW), ("known 2023-03..2026-03", 20230301, 20260331), ("all", 0, 99999999)]
        for name, a, b in spans:
            m = (dk >= a) & (dk <= b)
            if not m.any():
                continue
            s = lab4.describe(lab4.summary({"r": r[m], "kind": t["kind"][m], "day": t["day"][m]}, d["dkey"]))
            rows.append({"costs": label, "period": name, "n": s["n"], "win": round(s["win"], 4), "target_hit": round(s["tgt"], 4),
                         "avg_r": round(s["avg_r"], 4), "t": round(float(s["t"]), 2), "pf": round(s["pf"], 3)})
    new = next(x for x in rows if x["period"].startswith("NEW") and x["costs"].startswith("research"))
    verdict = "confirmed" if new["avg_r"] > 0 and new["t"] >= 2 else ("weak" if new["avg_r"] > 0 else "failed")
    days = d["dkey"]
    cover = {str(y): int(((days >= y * 10000) & (days < (y + 1) * 10000)).sum()) for y in range(2016, 2027)}
    OUT.mkdir(exist_ok=True)
    (OUT / "nb3_10y.json").write_text(json.dumps({"verdict_2016_2023": verdict, "sessions_per_year": cover, "rows": rows}, indent=1))
    lines = [f"Verdict for 2016-01..2023-02 (pre-registered rule): **{verdict}**", "",
             "| Costs | Period | Trades | Win rate | 3R hit | Avg R | t | PF |", "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {x['costs'].split(' (')[0]} | {x['period']} | {x['n']} | {100 * x['win']:.1f}% | {100 * x['target_hit']:.1f}% | "
              f"{x['avg_r']:+.3f} | {x['t']:.2f} | {x['pf']:.2f} |" for x in rows]
    (OUT / "nb3_10y.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


# ----------------------------------------------------------------------------- Part 2
def _init(inst):
    _D["d"] = load(inst)


def design_job(ex):
    stop, rr, mt = ex
    pool = lc.build_pool(_D["d"], *DESIGN, stop, rr, mt)
    st = lc.streams(pool, N, H, BLOCK, SEED)
    rows = []
    for es in EVAL_SIZES:
        for fs in FUND_SIZES:
            for keep in KEEPS:
                cfg = lc.Config(stop, rr, mt, es, fs, keep)
                rows.append({**cfg_row(cfg), **lc.metrics(lc.simulate(pool, st, cfg))})
    return rows


def cfg_row(cfg):
    return {"stop": cfg.stop, "rr": cfg.rr, "mt": cfg.mt, "eval_size": f"{cfg.eval_size[0]}:{cfg.eval_size[1]}",
            "funded_size": f"{cfg.funded_size[0]}:{cfg.funded_size[1]}", "keep": cfg.keep}


def row_cfg(r):
    def sz(x):
        k, v = x.split(":")
        return (k, float(v))
    return lc.Config(float(r["stop"]), float(r["rr"]), int(r["mt"]), sz(r["eval_size"]), sz(r["funded_size"]), float(r["keep"]))


def design(inst: str) -> None:
    t0 = time.time()
    OUT.mkdir(exist_ok=True)
    rows = []
    with Pool(4, initializer=_init, initargs=(inst,)) as p:
        for i, part in enumerate(p.imap_unordered(design_job, EXITS)):
            rows += part
            print(f"exit variants {i + 1}/{len(EXITS)} ({time.time() - t0:.0f}s)", flush=True)
    with open(OUT / "design_grid.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    best = max(rows, key=lambda r: (r["payout_12m"], r["net_mean"]))
    money = max(rows, key=lambda r: r["net_mean"])
    near = [r for r in rows if r["payout_12m"] >= best["payout_12m"] - 0.02]
    bal = max(near, key=lambda r: r["net_mean"])
    base = next(r for r in rows if row_cfg(r) == BASELINE)
    picks = {"1_max_payout_chance": best, "2_max_expected_cash": money, "3_balanced": bal, "baseline_bot": base}
    (OUT / "picks.json").write_text(json.dumps(picks, indent=1))
    for k, r in picks.items():
        print(k, json.dumps(r))


def check(inst: str) -> None:
    d = load(inst)
    picks = json.loads((OUT / "picks.json").read_text())
    out, lines = {}, []
    cases = [("check 2023-26, full edge", CHECK, 1.0, H), ("check 2023-26, half edge", CHECK, 0.5, H),
             ("design 2016-22, half edge", DESIGN, 0.5, H), ("check 2023-26, full edge, 24 months (extra)", CHECK, 1.0, 2 * H)]
    pools = {}
    for name, r in picks.items():
        cfg = row_cfg(r)
        key = (cfg.stop, cfg.rr, cfg.mt)
        out[name] = {"config": cfg_row(cfg), "design": {k: r[k] for k in r if k not in cfg_row(cfg)}}
        for label, span, keep, hz in cases:
            pk = key + span
            if pk not in pools:
                pools[pk] = lc.build_pool(d, *span, *key)
            st = lc.streams(pools[pk], N, hz, BLOCK, SEED + 1, edge_keep=keep)
            out[name][label] = lc.metrics(lc.simulate(pools[pk], st, cfg))
    (OUT / "check.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", required=True)
    ap.add_argument("stage", choices=("nb3", "design", "check"))
    a = ap.parse_args()
    if a.stage == "nb3":
        part1(load(a.inst))
    elif a.stage == "design":
        design(a.inst)
    else:
        check(a.inst)


if __name__ == "__main__":
    main()
