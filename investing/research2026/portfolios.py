"""Candidate portfolios (weights on the sleeves in sleeves.py) and historical backtest metrics.

Backtests run on daily euro total-return sleeve series (for drawdowns) and on monthly series (for rolling
windows), with the pie rebalanced to its targets on the first trading day of each calendar year.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# The ten portfolios the request asks for, plus benchmarks. Weights sum to 1. "STOCKS10" and the
# HINDSIGHT-flagged sleeves are chosen with today's knowledge, so their backtests are biased upward.
PORTFOLIOS = {
    "ORIGINAL": {"NDX": .40, "SEMI": .25, "NVDA": .15, "SPX": .10, "SPEC": .10},
    "DIVERSIFIED_GROWTH": {"WORLD": .40, "NDX": .20, "SCV": .10, "EM": .10, "SEMI": .10, "GOLD": .10},
    "SEMI_FOCUS": {"SEMI": .50, "NDX": .30, "SPX": .20},
    "NASDAQ": {"NDX": 1.0},
    "STOCKS10": {"MSFT": .10, "GOOGL": .10, "AMZN": .10, "META": .10, "NVDA": .10, "TSM": .10, "AVGO": .10,
                 "ASML": .10, "JPM": .10, "LLY": .10},
    "AI_INFRA": {"SEMI": .40, "NVDA": .15, "TECH": .15, "NDX": .15, "UTIL": .15},
    "GROWTH_QUALITY": {"NDX": .40, "QUALITY": .40, "HEALTH": .10, "GOLD": .10},
    "MOMENTUM": {"MOMENTUM": 1.0},
    "MIN_DOWNSIDE": {"WORLD": .45, "NDX": .10, "GOLD": .20, "CASH": .25},
    "CORE_SATELLITE": {"WORLD": .60, "NDX": .20, "SEMI": .10, "GOLD": .10},
    "SP500": {"SPX": 1.0},
    "WORLD": {"WORLD": 1.0},
    "LOW_RISK_50_50": {"WORLD": .50, "CASH": .50},
}
LABELS = {
    "ORIGINAL": "Original (40 Nasdaq / 25 semis / 15 NVDA / 10 S&P / 10 speculative)",
    "DIVERSIFIED_GROWTH": "Diversified high growth",
    "SEMI_FOCUS": "Semiconductor-focused",
    "NASDAQ": "Nasdaq-100 only (benchmark)",
    "STOCKS10": "Concentrated 10 stocks (hindsight-biased backtest)",
    "AI_INFRA": "AI infrastructure",
    "GROWTH_QUALITY": "Growth and quality",
    "MOMENTUM": "Momentum (sector rotation to May 2013, then MSCI USA Momentum)",
    "MIN_DOWNSIDE": "Downside-minimised growth",
    "CORE_SATELLITE": "Core-satellite (world core + Nasdaq/semis satellite)",
    "SP500": "S&P 500 only (benchmark)",
    "WORLD": "All-world only (VWCE)",
    "LOW_RISK_50_50": "Lower-risk benchmark: 50% world / 50% euro cash",
}


def weights_frame(port: dict, cols) -> pd.Series:
    w = pd.Series(0.0, index=cols)
    for k, v in port.items():
        w[k] = v
    return w


def run(returns: pd.DataFrame, port: dict, rebalance: str = "annual") -> pd.Series:
    """Value path (start 1.0) of a pie on a returns frame (daily or monthly), rebalanced at the first period
    of each calendar year ("annual"), never ("none"), or every period ("always"). Starts at the first
    period where every holding has data."""
    cols = list(port)
    r = returns[cols].dropna()
    w = np.array([port[c] for c in cols])
    hold = w.copy()
    vals = np.empty(len(r))
    year = None
    arr = r.to_numpy()
    for i, dt in enumerate(r.index):
        if rebalance == "always" or (rebalance == "annual" and dt.year != year and i > 0):
            hold = hold.sum() * w
        year = dt.year
        hold = hold * (1 + arr[i])
        vals[i] = hold.sum()
    return pd.Series(vals, index=r.index)


def drawdown_stats(v: pd.Series) -> dict:
    peak = v.cummax()
    dd = v / peak - 1
    i_trough = int(np.argmin(dd.to_numpy()))
    t_trough = dd.index[i_trough]
    t_peak = v.loc[:t_trough].idxmax()
    after = v.loc[t_trough:]
    rec = after[after >= v.loc[t_peak]]
    t_rec = rec.index[0] if len(rec) else None
    longest, cur, start = 0, 0, None
    under = (dd < 0).to_numpy()
    for i, u in enumerate(under):
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    return {"max_drawdown": float(dd.min()), "peak": str(t_peak.date()), "trough": str(t_trough.date()),
            "recovered": str(t_rec.date()) if t_rec is not None else None,
            "months_peak_to_recovery": (round((t_rec - t_peak).days / 30.44, 1) if t_rec is not None else None),
            "months_trough_to_recovery": (round((t_rec - t_trough).days / 30.44, 1) if t_rec is not None else None)}


def metrics(v_daily: pd.Series, v_month: pd.Series, cash_m: pd.Series) -> dict:
    """Full metric set; Sharpe and Sortino use monthly returns in excess of euro cash."""
    yrs = (v_daily.index[-1] - v_daily.index[0]).days / 365.25
    total = v_daily.iloc[-1] / v_daily.iloc[0] - 1
    rm = v_month.pct_change().dropna()
    c = cash_m.reindex(rm.index).fillna(0)
    ex = rm - c
    down = np.minimum(ex, 0)
    roll12 = v_month / v_month.shift(12) - 1
    roll24 = (v_month / v_month.shift(24) - 1).dropna()
    out = {
        "start": str(v_daily.index[0].date()), "end": str(v_daily.index[-1].date()), "years": round(yrs, 2),
        "cagr": (1 + total) ** (1 / yrs) - 1, "total_return": total,
        "vol": float(rm.std() * np.sqrt(12)),
        "sharpe": float(ex.mean() / ex.std() * np.sqrt(12)) if ex.std() > 0 else None,
        "sortino": float(ex.mean() * 12 / (np.sqrt((down ** 2).mean()) * np.sqrt(12))) if (down ** 2).mean() > 0 else None,
        "worst_1y": float(roll12.min()), "worst_2y": float(roll24.min()), "best_2y": float(roll24.max()),
        "rolling_2y_windows": int(len(roll24)),
        "p2y_gain": float((roll24 > 0).mean()), "p2y_ge50": float((roll24 >= 0.5).mean()),
        "p2y_ge100": float((roll24 >= 1.0).mean()), "p2y_loss20": float((roll24 <= -0.2).mean()),
        "p2y_loss40": float((roll24 <= -0.4).mean()), "p2y_loss60": float((roll24 <= -0.6).mean()),
        "median_2y": float(roll24.median()),
    }
    out.update(drawdown_stats(v_daily))
    return out


CRISES = {
    "dotcom_2000_02": ("2000-09-01", "2003-03-31", "Sep 2000 - Mar 2003 (the window starts 6 months after the March 2000 peak)"),
    "gfc_2007_09": ("2007-10-01", "2009-06-30", "Oct 2007 - Jun 2009"),
    "covid_2020": ("2020-02-19", "2020-06-30", "19 Feb - 30 Jun 2020"),
    "tech_2022": ("2021-11-19", "2022-12-31", "19 Nov 2021 - Dec 2022"),
    "tariff_2025": ("2025-02-19", "2025-06-30", "19 Feb - 30 Jun 2025"),
    "y2026_to_date": ("2026-01-01", "2026-11-18", "1 Jan - 18 Nov 2026"),
}


def crisis_table(daily: pd.DataFrame, port: dict) -> dict:
    out = {}
    for k, (a, b, _) in CRISES.items():
        sub = daily.loc[a:b]
        if sub[list(port)].dropna().shape[0] < 20:
            out[k] = None
            continue
        v = run(sub, port, "none")
        dd = (v / v.cummax() - 1).min()
        out[k] = {"max_drawdown": float(dd), "window_return": float(v.iloc[-1] - 1)}
    return out
