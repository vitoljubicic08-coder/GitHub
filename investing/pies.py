#!/usr/bin/env python3
"""Backtest candidate investment "pies" on daily total-return prices (dividends reinvested, Yahoo
adjusted closes), with US ETFs standing in for their European UCITS equivalents.

  python3 -I investing/pies.py --prices <adj_close.csv>

Annual rebalancing on the first trading day of each year. Returns are in US dollars; a euro investor
also carries the EUR/USD exchange rate. Past returns, especially the US tech decade, do not predict
future returns.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

PIES = {
    "Simple global (VWCE)": {"SPY": 0.62, "EFA": 0.28, "EEM": 0.10},
    "100% S&P 500 (CSPX)": {"SPY": 1.0},
    "Max growth": {"SPY": 0.40, "QQQ": 0.30, "SMH": 0.15, "IJS": 0.15},
    "Growth + guardrails": {"SPY": 0.28, "EFA": 0.12, "EEM": 0.05, "QQQ": 0.25, "SMH": 0.10, "IJS": 0.10, "GLD": 0.10},
    "All-in tech (hindsight winner)": {"QQQ": 0.5, "SMH": 0.5},
}
LEVERAGED = ("3x Nasdaq-100 (daily reset, simulated)", "QQQ", 3.0, 0.03)   # 3% a year fees + financing drag


def pie_value(px: pd.DataFrame, w: dict) -> pd.Series:
    sub = px[list(w)].dropna()
    rets = sub.pct_change().fillna(0.0)
    val, out = 1.0, []
    hold = {k: w[k] for k in w}
    year = None
    for dt, r in rets.iterrows():
        if dt.year != year:                         # rebalance at the first day of each year
            year = dt.year
            hold = {k: val * w[k] for k in w}
        hold = {k: v * (1 + r[k]) for k, v in hold.items()}
        val = sum(hold.values())
        out.append(val)
    return pd.Series(out, index=rets.index)


def leveraged(px, tk, lev, drag):
    r = px[tk].dropna().pct_change().fillna(0.0)
    return (1 + lev * r - drag / 252).clip(lower=0).cumprod()


def stats(v: pd.Series, start, end=None) -> dict:
    v = v.loc[start:end]
    v = v / v.iloc[0]
    yrs = (v.index[-1] - v.index[0]).days / 365.25
    dd = v / v.cummax() - 1
    under, longest, cur = (v < v.cummax()), 0, 0
    for u in under:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    yearly = v.resample("YE").last().pct_change().dropna()
    first = v.resample("YE").last().iloc[0] / v.iloc[0] - 1
    yearly = pd.concat([pd.Series([first], index=[v.resample("YE").last().index[0]]), yearly])
    dr = v.pct_change().dropna()
    m = v.resample("ME").last()
    roll10 = (m / m.shift(120)) ** (1 / 10) - 1
    return {"from": str(v.index[0].date()), "to": str(v.index[-1].date()), "cagr": float(v.iloc[-1] ** (1 / yrs) - 1),
            "end_value_of_5000": float(5000 * v.iloc[-1]), "max_drawdown": float(dd.min()),
            "longest_underwater_years": round(longest / 252, 1), "worst_year": float(yearly.min()),
            "worst_year_date": int(yearly.idxmin().year), "best_year": float(yearly.max()),
            "volatility": float(dr.std() * np.sqrt(252)), "sharpe_0rf": float(dr.mean() / dr.std() * np.sqrt(252)),
            "rolling10_min": float(roll10.min()) if roll10.notna().any() else None,
            "rolling10_median": float(roll10.median()) if roll10.notna().any() else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", required=True)
    a = ap.parse_args()
    px = pd.read_csv(a.prices, index_col=0, parse_dates=True)
    series = {name: pie_value(px, w) for name, w in PIES.items()}
    series[LEVERAGED[0]] = leveraged(px, *LEVERAGED[1:])
    windows = {"2005-2026 (includes 2008, 2020, 2022)": ("2005-01-03", None),
               "2000-2026 (includes the dot-com crash)": ("2000-08-01", None),
               "2016-2026 (the recent boom)": ("2016-01-04", None)}
    out = {}
    for wname, (s, e) in windows.items():
        print(f"\n=== {wname}")
        print(f"{'pie':40s} {'$5,000 ->':>11s} {'per yr':>7s} {'worst fall':>10s} {'yrs under water':>15s} {'worst year':>11s} {'10y worst/median':>17s}")
        out[wname] = {}
        for name, v in series.items():
            if v.index[0] > pd.Timestamp(s) + pd.Timedelta(days=10):
                continue
            st = stats(v, s, e)
            out[wname][name] = st
            r10 = f"{100 * st['rolling10_min']:+.1f}%/{100 * st['rolling10_median']:+.1f}%" if st["rolling10_min"] is not None else "-"
            print(f"{name:40s} {st['end_value_of_5000']:>11,.0f} {100 * st['cagr']:+6.1f}% {100 * st['max_drawdown']:9.0f}% "
                  f"{st['longest_underwater_years']:15.1f} {100 * st['worst_year']:+7.0f}% ({st['worst_year_date']}) {r10:>17s}")
    Path(__file__).with_name("pies_results.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
