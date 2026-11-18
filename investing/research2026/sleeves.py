"""Monthly and daily euro total-return series for the building blocks ("sleeves") of the candidate portfolios.

Each sleeve is a long-history US-listed proxy (Yahoo adjusted close = dividends reinvested), converted to
euros with the Fed H.10 noon rate (FRED DEXUSEU, from 1999), then shifted by the measured tracking gap
between the proxy (in euros) and the UCITS fund a Croatian investor would actually buy on Xetra. The gap
captures the UCITS fund's fee and its dividend withholding tax. Euro cash earns EONIA (1999-2019) and then
EUR STR (ECB data portal).

Proxy choices (and their known weaknesses) are listed in SLEEVES; see docs in the report, section 16.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# sleeve -> (proxy series built from the Yahoo download, UCITS line used for the tracking check, description)
SLEEVES = {
    "WORLD": ("world", "VWCE.DE", "All-world equity: 50% SPY + 50% VGTSX to Mar 2008, then ACWI (proxy for VWCE)"),
    "SPX": ("SPY", "SXR8.DE", "S&P 500 (proxy for iShares Core S&P 500, SXR8)"),
    "NDX": ("QQQ", "SXRV.DE", "Nasdaq-100 (proxy for iShares Nasdaq 100, SXRV)"),
    "SEMI": ("SMH", "VVSM.DE", "US-listed semiconductors (proxy for VanEck Semiconductor UCITS, VVSM)"),
    "NVDA": ("NVDA", None, "Nvidia shares (bought directly; USD line)"),
    "SPEC": ("IWO", None, "Speculative high growth: Russell 2000 Growth (IWO) as a long-history proxy"),
    "ARKK": ("ARKK", None, "ARK Innovation (from Nov 2014): alternative speculative proxy"),
    "SCV": ("IJS", "ZPRV.DE", "US small-cap value (S&P 600 Value, IJS; proxy for ZPRV)"),
    "EM": ("em", "IS3N.DE", "Emerging markets: VEIEX to Apr 2003, then EEM (proxy for IS3N)"),
    "EUROPE": ("EZU", None, "Euro-area equity (MSCI EMU, EZU)"),
    "GOLD": ("gold", "4GLD.DE", "Gold: front-month futures GC=F to Nov 2004, then GLD (proxy for Xetra-Gold / IGLN)"),
    "TECH": ("XLK", "QDVE.DE", "S&P 500 Information Technology (XLK; proxy for QDVE)"),
    "HEALTH": ("XLV", None, "S&P 500 Health Care (XLV)"),
    "STAPLES": ("XLP", None, "S&P 500 Consumer Staples (XLP)"),
    "UTIL": ("XLU", None, "S&P 500 Utilities (XLU)"),
    "ENERGY": ("XLE", None, "S&P 500 Energy (XLE)"),
    "QUALITY": ("QUAL", "IS3Q.DE", "MSCI USA Quality (from Jul 2013)"),
    "MOMENTUM": ("momentum", "IS3R.DE", "Momentum: top-3 S&P sectors by 12-1 month return to May 2013, then MSCI USA Momentum (MTUM)"),
    "MEGA8": ("mega8", None, "Equal-weight NVDA, MSFT, AAPL, GOOGL, AMZN, META, AVGO, TSM (from Jun 2012; HINDSIGHT)"),
    "CASH": ("cash", "XEON.DE", "Euro cash: EONIA, then EUR STR (proxy for XEON)"),
    # Phase 2 candidates
    "MIDGROWTH": ("IJK", None, "US mid-cap growth (S&P MidCap 400 Growth, IJK; no UCITS equivalent found)"),
    "MIDCAP": ("MDY", None, "US mid caps (S&P MidCap 400, MDY; proxy for iShares Core S&P Mid Cap 400 UCITS)"),
    "QUALITY_SP": ("SPHQ", None, "S&P 500 Quality (SPHQ, from Dec 2005; quality proxy that covers 2008)"),
    "EQW": ("RSP", "XDEW.DE", "S&P 500 Equal Weight (RSP, from May 2003; proxy for XDEW)"),
    "LOWVOL": ("USMV", None, "MSCI USA Minimum Volatility (USMV, from Oct 2011; proxy for MSCI World Min Vol UCITS)"),
    "SOFTWARE": ("IGV", None, "North American software (IGV, from Jul 2001; no UCITS equivalent checked)"),
}
MEGA8 = ["NVDA", "MSFT", "AAPL", "GOOGL", "AMZN", "META", "AVGO", "TSM"]
STOCKS = ["MSFT", "AAPL", "GOOGL", "AMZN", "META", "AVGO", "TSM", "AMD", "ASML", "MU", "ORCL", "PLTR", "TSLA",
          "NFLX", "LLY", "NVO", "JPM", "V", "MA", "COST", "BRK-B", "UNH", "SAP"]          # NVDA is its own sleeve
SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]


def _fred(path: Path) -> pd.Series:
    df = pd.read_csv(path)
    s = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    s.index = pd.to_datetime(df.iloc[:, 0])
    return s.dropna()


def _ecb(path: Path) -> pd.Series:
    df = pd.read_csv(path)
    s = pd.Series(pd.to_numeric(df["OBS_VALUE"], errors="coerce").values, index=pd.to_datetime(df["TIME_PERIOD"]))
    return s.dropna().sort_index()


def load_raw(cache: Path):
    px = pd.read_csv(cache / "adj_close.csv", index_col=0, parse_dates=True).sort_index()
    fx = _fred(cache / "macro" / "fred_DEXUSEU.csv")                    # USD per EUR
    eonia = _ecb(cache / "macro" / "ecb_eonia.csv")
    estr = _ecb(cache / "macro" / "ecb_estr.csv")
    rate = pd.concat([eonia[eonia.index < estr.index[0]], estr]).sort_index()   # % per year, act/360
    return px, fx, rate


def daily_usd_returns(px: pd.DataFrame) -> pd.DataFrame:
    """Daily simple returns in the listing currency for the series the sleeves need (US trading days)."""
    us = px[px["SPY"].notna()].copy()
    r = us.pct_change(fill_method=None)
    out = {}
    for t in ("SPY", "QQQ", "SMH", "NVDA", "IWO", "ARKK", "IJS", "EZU", "XLK", "XLV", "XLP", "XLU", "XLE", "QUAL", "MTUM",
              "IJK", "MDY", "SPHQ", "RSP", "USMV", "IGV"):
        if t in r:
            out[t] = r[t]
    world = 0.5 * r["SPY"] + 0.5 * r["VGTSX"]                           # daily-rebalanced 50/50 before ACWI
    world[r.index >= "2008-04-01"] = r["ACWI"][r.index >= "2008-04-01"]
    out["world"] = world
    em = r["VEIEX"].copy()
    em[r.index >= "2003-05-01"] = r["EEM"][r.index >= "2003-05-01"]
    out["em"] = em
    gold = r["GC=F"].copy()
    gold[r.index >= "2004-12-01"] = r["GLD"][r.index >= "2004-12-01"]
    out["gold"] = gold
    m8 = r[MEGA8]
    out["mega8"] = m8.mean(axis=1, skipna=False)                         # daily-rebalanced equal weight
    for t in STOCKS:
        out[t] = r[t]
    mom = sector_momentum(us[SECTORS], r[SECTORS])
    m = r["MTUM"].copy()
    m[r.index < "2013-06-01"] = mom[r.index < "2013-06-01"]
    out["momentum"] = m
    return pd.DataFrame(out)


def sector_momentum(prices: pd.DataFrame, rets: pd.DataFrame, top: int = 3) -> pd.Series:
    """Point-in-time sector momentum: at each month end hold, for the next month, the `top` S&P sector
    SPDRs with the best return from 12 months to 1 month ago (equal weight). No future data is used."""
    me = prices.resample("ME").last()
    score = me.shift(1) / me.shift(12) - 1
    out = pd.Series(np.nan, index=rets.index)
    for i in range(12, len(me) - 1):
        sc = score.iloc[i].dropna()
        if len(sc) < len(SECTORS):
            continue
        pick = list(sc.sort_values(ascending=False).index[:top])
        a, b = me.index[i], me.index[i + 1]
        mask = (rets.index > a) & (rets.index <= b)
        out[mask] = rets.loc[mask, pick].mean(axis=1)
    return out


def to_eur(r_usd: pd.DataFrame, fx: pd.Series) -> pd.DataFrame:
    f = fx.reindex(r_usd.index).ffill()
    fx_ret = f / f.shift(1)                                              # USD per EUR, so EUR value = USD / f
    return (1 + r_usd).div(fx_ret, axis=0) - 1


def cash_daily(rate: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    rr = rate.reindex(index.union(rate.index)).sort_index().ffill().reindex(index)
    days = pd.Series(index, index=index).diff().dt.days.fillna(1)
    return (rr.shift(1).bfill() / 100.0) * days / 360.0


def build(cache: Path, start="2000-09-01"):
    """Daily euro returns per sleeve (before UCITS cost shift), plus the raw prices for tracking checks."""
    px, fx, rate = load_raw(cache)
    r = to_eur(daily_usd_returns(px), fx)
    r["cash"] = cash_daily(rate, r.index)
    r = r[r.index >= pd.Timestamp(start) - pd.Timedelta(days=7)]
    names = {}
    for sl, (src, _, _) in SLEEVES.items():
        names[sl] = r[src] if src in r else r[src.lower()]
    for t in STOCKS:
        names[t] = r[t]
    daily = pd.DataFrame(names)
    return daily, px, fx


def monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """Month-end compounding; a month with any missing day for a sleeve is NaN for that sleeve."""
    g = daily.groupby(daily.index.to_period("M"))
    out = g.apply(lambda x: (1 + x).prod(min_count=1) - 1)
    cnt = g.count()
    full = g.size()
    out = out.where(cnt.ge(full.values[:, None] * 0.9))
    out.index = out.index.to_timestamp("M")
    return out


def tracking_gaps(daily_eur: pd.DataFrame, px: pd.DataFrame) -> dict:
    """Annualised return of UCITS line minus its proxy (both in EUR), over their common full months."""
    res = {}
    pm = px.copy()
    pm.index = pd.to_datetime(pm.index)
    pm = pm.resample("ME").last()
    sl_m = monthly(daily_eur)
    for sl, (_, ucits, _) in SLEEVES.items():
        if not ucits or ucits not in pm:
            continue
        u = pm[ucits].pct_change(fill_method=None)
        p = sl_m[sl]
        both = pd.concat([u, p], axis=1, keys=["u", "p"]).dropna()
        both = both.iloc[1:]                                             # first month may be partial
        both = both[both.index >= "2011-01-31"]                         # Yahoo's 2010 Xetra prices are bad
        if len(both) < 24:
            continue
        yrs = len(both) / 12
        gu = (1 + both["u"]).prod() ** (1 / yrs) - 1
        gp = (1 + both["p"]).prod() ** (1 / yrs) - 1
        corr = both.corr().iloc[0, 1]
        te = (both["u"] - both["p"]).std() * np.sqrt(12)
        res[sl] = {"ucits": ucits, "months": len(both), "from": str(both.index[0].date()), "ucits_cagr": gu,
                   "proxy_cagr": gp, "gap": gu - gp, "corr": corr, "tracking_error": te}
    return res


# annual drag applied to a sleeve when no UCITS line has enough history to measure the gap: an assumption
# (15% US dividend withholding on a ~1.5% yield plus ~0.1% extra fee); noted in the report.
DEFAULT_DRAG = 0.003


def cost_shift(gaps: dict) -> dict:
    """Annual return shift per sleeve. A measured gap is used only with >= 10 years of overlap (shorter
    overlaps are dominated by the 17:30 Xetra vs 16:00 New York closing-time noise) and |gap| <= 1% (larger
    gaps are index differences, not costs); a positive gap is never credited. Otherwise DEFAULT_DRAG.
    NVDA is bought directly (no fund cost); euro cash pays XEON's 0.10% fee."""
    shift = {t: -0.001 for t in STOCKS}                                  # 15% US withholding on small dividends
    for sl in SLEEVES:
        if sl == "CASH":
            shift[sl] = -0.001
        elif sl == "NVDA":
            shift[sl] = 0.0
        elif sl in gaps and gaps[sl]["months"] >= 120 and abs(gaps[sl]["gap"]) <= 0.01:
            shift[sl] = min(gaps[sl]["gap"], 0.0)
        else:
            shift[sl] = -DEFAULT_DRAG
    return shift


def apply_shift(df: pd.DataFrame, shift: dict, periods_per_year: int) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        out[c] = (1 + out[c]) * (1 + shift.get(c, 0.0)) ** (1 / periods_per_year) - 1
    return out
