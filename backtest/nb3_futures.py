#!/usr/bin/env python3
"""Part 3: does NB3 V2 transfer from QQQ to NQ/MNQ (and SPY to ES/MES)?

Uses the Yahoo Sep-Nov 2026 caches (5-minute bars on the 1-minute grid, regular session only):
  * price-ratio and return correlation between the ETF and the future;
  * signal agreement when NB3 runs on each instrument's own data;
  * NB3 run directly on the future (future ticks and costs);
  * cross-instrument execution: ETF signal -> futures fill, stop from the future's own ATR.
Writes backtest/results_nb3v2/futures.json.
Usage: python3 backtest/nb3_futures.py --fut <futures cache> --etf <Yahoo ETF cache>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import intraday_lab as il  # noqa: E402
import nb3_trades as nt  # noqa: E402

# micro contracts: $2/pt MNQ, $5/pt MES; commission ~$0.61 per side (Topstep's $1.22 round turn)
FUT_EXEC = {"NQ": nt.Exec(slip_ticks=1, tick=0.25, commission=0.61 / 2.0),
            "ES": nt.Exec(slip_ticks=1, tick=0.25, commission=0.61 / 5.0)}
PAIRS = (("QQQ", "NQ"), ("SPY", "ES"))


def align(a: dict, b: dict) -> tuple[dict, dict]:
    common = np.intersect1d(a["dkey"], b["dkey"])
    pick = lambda d: {k: (v[np.isin(d["dkey"], common)] if isinstance(v, np.ndarray) and len(v) == len(d["dkey"]) else v)
                      for k, v in d.items()}
    return pick(a), pick(b)


def summ(tr: list) -> dict:
    if not tr:
        return {"trades": 0}
    r = np.array([t.r_net for t in tr])
    return {"trades": len(r), "mean_r": float(r.mean()), "win_rate": float((r > 0).mean()),
            "total_r": float(r.sum()), "t_stat": float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 2 else None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fut", required=True)
    ap.add_argument("--etf", required=True)
    ap.add_argument("--out", default="backtest/results_nb3v2/futures.json")
    args = ap.parse_args()
    res = {}
    for etf, fut in PAIRS:
        e, f = align(il.load_instrument(args.etf, etf), il.load_instrument(args.fut, fut))
        ce, cf_ = e["cf"][:, :il.EOD_MIN], f["cf"][:, :il.EOD_MIN]
        m = ~np.isnan(ce) & ~np.isnan(cf_)
        ratio = cf_[m] / ce[m]
        r5e, r5f = np.diff(ce[:, ::5], axis=1), np.diff(cf_[:, ::5], axis=1)
        ok = ~np.isnan(r5e) & ~np.isnan(r5f)
        de, df_ = r5e[ok] / ce[:, ::5][:, :-1][ok], r5f[ok] / cf_[:, ::5][:, :-1][ok]
        se, sf = il.signals(e, "noise_break", 1.0), il.signals(f, "noise_break", 1.0)
        first = lambda s: [(int(np.flatnonzero(row)[0]), int(row[np.flatnonzero(row)[0]])) if row.any() else None
                           for row in (s * ((np.arange(78) + 1) * 5 < 330))]
        fe, ff = first(se), first(sf)
        both = [(a, b) for a, b in zip(fe, ff) if a and b]
        tr_e = nt.extract(e)
        tr_f = nt.extract(f, ex=FUT_EXEC[fut])
        tr_x = nt.extract(f, ex=FUT_EXEC[fut], sig=se)          # ETF signal, futures execution
        days_e = {t.dkey for t in tr_e}
        x_by = {t.dkey: t.r_net for t in tr_x}
        e_by = {t.dkey: t.r_net for t in tr_e}
        same = sorted(days_e & set(x_by))
        res[f"{etf}->{fut}"] = {
            "days": int(len(e["dkey"])), "first_day": int(e["dkey"][0]), "last_day": int(e["dkey"][-1]),
            "price_ratio": {"median": float(np.median(ratio)), "min": float(ratio.min()), "max": float(ratio.max())},
            "corr_5min_returns": float(np.corrcoef(de, df_)[0, 1]),
            "signal_days_etf": int(sum(a is not None for a in fe)), "signal_days_future": int(sum(b is not None for b in ff)),
            "signal_days_both": len(both),
            "same_direction": float(np.mean([a[1] == b[1] for a, b in both])) if both else None,
            "same_bar": float(np.mean([a[0] == b[0] for a, b in both])) if both else None,
            "bar_diff_median": float(np.median([abs(a[0] - b[0]) for a, b in both])) if both else None,
            "etf_own_signals": summ(tr_e),
            "etf_own_signals_same_days": summ([t for t in tr_e if t.dkey in x_by]), "future_own_signals": summ(tr_f), "etf_signal_future_execution": summ(tr_x),
            "per_trade_r_corr_etf_vs_cross": float(np.corrcoef([e_by[k] for k in same], [x_by[k] for k in same])[0, 1]) if len(same) > 2 else None,
            "stop_points_median": float(np.median([t.dist for t in tr_f])) if tr_f else None,
        }
    # dollars of risk for one micro at the future's own stop
    res["QQQ->NQ"]["one_MNQ_stop_usd_median"] = res["QQQ->NQ"]["stop_points_median"] * 2.0
    res["SPY->ES"]["one_MES_stop_usd_median"] = res["SPY->ES"]["stop_points_median"] * 5.0
    Path(args.out).write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
