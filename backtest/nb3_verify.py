#!/usr/bin/env python3
"""Part 1: independent verification of NB3 V2 (band 1.0, stop 0.30 x prev ATR, 1:3, first signal/day).

Writes backtest/results_nb3v2/verify.json and prints a summary. All randomness uses fixed seeds.
Usage: python3 backtest/nb3_verify.py --inst <inst cache> --yahoo <yahoo market cache>
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import intraday_lab as il  # noqa: E402
import nb3_trades as nt  # noqa: E402

PERIODS = {"dev": (20230301, 20241231), "holdout": (20250101, 20260331), "full": (0, 20260331)}


def stats(tr: list[nt.Trade], n_days: int) -> dict:
    if not tr:
        return {"trades": 0}
    r = np.array([t.r_net for t in tr]); g = np.array([t.r_gross for t in tr])
    reasons = [t.reason for t in tr]
    wins, losses = r[r > 0], r[r <= 0]
    cum = np.cumsum(r); dd = float((cum - np.maximum.accumulate(np.r_[0, cum])[1:]).min())
    streak = best = 0
    for x in r <= 0:
        streak = streak + 1 if x else 0; best = max(best, streak)
    srt = np.sort(r)[::-1]
    def top_share(p):
        k = max(1, int(round(len(r) * p)))
        return float(srt[:k].sum() / r.sum()) if r.sum() != 0 else float("nan")
    return {
        "trades": int(len(r)), "trading_days": n_days, "trades_per_day": len(r) / n_days,
        "win_rate": float((r > 0).mean()), "target_rate": reasons.count("TARGET") / len(r),
        "stop_rate": (reasons.count("STOP") + reasons.count("STOPGAP")) / len(r), "eod_rate": reasons.count("EOD") / len(r),
        "avg_win_r": float(wins.mean()) if len(wins) else 0.0, "avg_loss_r": float(losses.mean()) if len(losses) else 0.0,
        "payoff": float(wins.mean() / -losses.mean()) if len(wins) and len(losses) else float("nan"),
        "mean_r": float(r.mean()), "median_r": float(np.median(r)), "std_r": float(r.std(ddof=1)),
        "t_stat": float(r.mean() / (r.std(ddof=1) / math.sqrt(len(r)))),
        "pf": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "gross_mean_r": float(g.mean()), "cost_per_trade_r": float(g.mean() - r.mean()),
        "total_r": float(r.sum()), "max_drawdown_r": dd, "longest_losing_streak": best,
        "top1pct_share": top_share(0.01), "top5pct_share": top_share(0.05), "top10pct_share": top_share(0.10),
        "mean_r_without_top5pct": float(srt[max(1, int(round(len(r) * 0.05))):].mean()),
        "long": {"n": int(sum(t.direction > 0 for t in tr)), "mean_r": float(np.mean([t.r_net for t in tr if t.direction > 0]))},
        "short": {"n": int(sum(t.direction < 0 for t in tr)), "mean_r": float(np.mean([t.r_net for t in tr if t.direction < 0]))},
    }


def in_period(tr, a, b):
    return [t for t in tr if a <= t.dkey <= b]


def bootstrap_ci(r, rng, n=10000):
    means = np.array([rng.choice(r, len(r)).mean() for _ in range(n)])
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)), float((means <= 0).mean())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", required=True)
    ap.add_argument("--yahoo", required=True)
    ap.add_argument("--out", default="backtest/results_nb3v2/verify.json")
    args = ap.parse_args()
    rng = np.random.default_rng(20261116)
    d = il.load_instrument(args.inst, "QQQ")
    tr = nt.extract(d)
    res: dict = {"rules": {"band": 1.0, "stop_atr": 0.30, "rr": 3.0, "first_signal_per_day": True,
                           "signal_bars": "09:30-14:50 open time", "exit": "stop / target / 15:55"}}
    days_in = lambda a, b: int(((d["dkey"] >= a) & (d["dkey"] <= b)).sum())
    for name, (a, b) in PERIODS.items():
        res[name] = stats(in_period(tr, a, b), days_in(a, b))
    yd = il.load_instrument(args.yahoo, "QQQ")
    ytr = [t for t in nt.extract(yd) if t.dkey <= 20261113]
    res["yahoo_sep_nov_2026"] = stats(ytr, int((yd["dkey"] <= 20261113).sum()) - 14)

    # regimes: by year, by volatility tercile (prev ATR / open), by month direction of QQQ
    res["by_year"] = {}
    for y in sorted({t.dkey // 10000 for t in tr}):
        sub = [t for t in tr if t.dkey // 10000 == y]
        res["by_year"][y] = {"trades": len(sub), "mean_r": float(np.mean([t.r_net for t in sub])), "total_r": float(sum(t.r_net for t in sub)),
                              "win_rate": float(np.mean([t.r_net > 0 for t in sub]))}
    pos = {int(k): i for i, k in enumerate(d["dkey"])}
    volp = np.array([d["atr_prev"][pos[t.dkey]] / d["day_open"][pos[t.dkey]] for t in tr])
    q1, q2 = np.percentile(volp, [33.3, 66.7])
    res["by_volatility"] = {}
    for name, m in (("low", volp <= q1), ("mid", (volp > q1) & (volp <= q2)), ("high", volp > q2)):
        rr_ = np.array([t.r_net for t in tr])[m]
        res["by_volatility"][name] = {"trades": int(m.sum()), "mean_r": float(rr_.mean()), "win_rate": float((rr_ > 0).mean()),
                                      "atr_pct_range": [float(volp[m].min() * 100), float(volp[m].max() * 100)]}
    mon = d["dkey"] // 100
    first_open = {m: d["day_open"][mon == m][0] for m in np.unique(mon)}
    last_close = {m: d["cf"][mon == m][-1, il.EOD_MIN - 1] for m in np.unique(mon)}
    mret = {int(m): last_close[m] / first_open[m] - 1 for m in first_open}
    res["by_market_month"] = {}
    for name, cond in (("QQQ month up", lambda x: x > 0), ("QQQ month down", lambda x: x <= 0)):
        sub = [t.r_net for t in tr if cond(mret[t.dkey // 100])]
        res["by_market_month"][name] = {"trades": len(sub), "mean_r": float(np.mean(sub)), "months": int(sum(cond(v) for v in mret.values()))}
    ho = np.array([t.r_net for t in in_period(tr, *PERIODS["holdout"])])
    no_apr25 = np.array([t.r_net for t in in_period(tr, *PERIODS["holdout"]) if t.dkey // 100 != 202504])
    res["holdout_without_april_2025"] = {"trades": int(len(no_apr25)), "mean_r": float(no_apr25.mean())}

    # costs and execution stress (re-simulated, not scaled)
    res["stress"] = {}
    cases = {"as tested (2 ticks, $0.005/sh)": nt.Exec(), "no costs": nt.Exec(slip_ticks=0, commission=0),
             "1 tick": nt.Exec(slip_ticks=1), "3 ticks": nt.Exec(slip_ticks=3), "4 ticks": nt.Exec(slip_ticks=4),
             "commission x2": nt.Exec(commission=0.01), "entry 1 bar late": nt.Exec(entry_delay_bars=1),
             "target needs 1-tick trade-through": nt.Exec(target_through_ticks=1),
             "10% entries missed": nt.Exec(miss_prob=0.10),
             "combined stress (3 ticks, late entry, trade-through, 5% missed)": nt.Exec(slip_ticks=3, entry_delay_bars=1, target_through_ticks=1, miss_prob=0.05)}
    for name, ex in cases.items():
        st = nt.extract(d, ex=ex, rng=np.random.default_rng(7))
        res["stress"][name] = {p: float(np.mean([t.r_net for t in in_period(st, *PERIODS[p])])) for p in ("dev", "holdout", "full")}

    # parameter neighbourhood (is V2 an isolated peak?)
    res["neighbourhood"] = []
    for band in (0.75, 1.0, 1.25, 1.5):
        sig = il.signals(d, "noise_break", band)
        for stop in (0.2, 0.25, 0.3, 0.35, 0.4):
            for rr in (2.0, 3.0):
                st = nt.extract(d, band=band, stop_atr=stop, rr=rr, sig=sig)
                res["neighbourhood"].append({"band": band, "stop": stop, "rr": rr,
                                             **{p: float(np.mean([t.r_net for t in in_period(st, *PERIODS[p])])) for p in ("dev", "holdout")}})

    # significance: bootstrap CI, sign-flip permutation (does the direction carry information?)
    res["significance"] = {}
    for p in ("dev", "holdout", "full"):
        r = np.array([t.r_net for t in in_period(tr, *PERIODS[p])])
        lo, hi, p0 = bootstrap_ci(r, rng)
        res["significance"][p] = {"mean_r": float(r.mean()), "ci95": [lo, hi], "bootstrap_p_mean_le_0": p0,
                                  "t_stat": float(r.mean() / (r.std(ddof=1) / math.sqrt(len(r))))}
    flip = nt.extract(d, sig=-il.signals(d, "noise_break", 1.0))
    by_day = {t.dkey: t.r_net for t in tr}; by_day_flip = {t.dkey: t.r_net for t in flip}
    common = sorted(set(by_day) & set(by_day_flip))
    for p in ("dev", "holdout", "full"):
        a, b = PERIODS[p]
        ks = [k for k in common if a <= k <= b]
        real = np.array([by_day[k] for k in ks]); opp = np.array([by_day_flip[k] for k in ks])
        perms = np.array([np.where(rng.random(len(ks)) < 0.5, real, opp).mean() for _ in range(10000)])
        res["significance"][p]["opposite_direction_mean_r"] = float(opp.mean())
        res["significance"][p]["random_direction_mean_r"] = float(perms.mean())
        res["significance"][p]["permutation_p"] = float((perms >= real.mean()).mean())
    # deflated-Sharpe style haircut: expected best per-trade Sharpe among N independent null trials
    n_trades = len(ho)
    for n_trials in (100, 1000, 31000):
        z = math.sqrt(2 * math.log(n_trials))
        exp_max_sr = z / math.sqrt(n_trades)      # approx. E[max SR] under the null, per trade
        res["significance"].setdefault("deflated", {})[str(n_trials)] = {
            "holdout_sr_per_trade": float(ho.mean() / ho.std(ddof=1)), "expected_max_null_sr": exp_max_sr}

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps({k: res[k] for k in ("dev", "holdout", "full", "yahoo_sep_nov_2026")}, indent=1, default=float)[:6000])


if __name__ == "__main__":
    main()
