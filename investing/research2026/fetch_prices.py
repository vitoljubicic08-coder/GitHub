#!/usr/bin/env python3
"""Download daily adjusted closes (dividends reinvested) from Yahoo Finance via yfinance.

  python3 -I investing/research2026/fetch_prices.py --out <cache dir>

Writes <out>/adj_close.csv (one column per ticker, as downloaded) and <out>/fetch_log.json. The data are
third-party and are not committed to the repository; rerun this script to rebuild them.
"""
import argparse
import json
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

GROUPS = {
    # US-listed ETFs used as long-history proxies for the UCITS funds a European investor actually buys
    "us_etf": ["SPY", "QQQ", "IWM", "IWO", "IWF", "IJS", "EFA", "EEM", "ACWI", "VT", "VEU", "VGK", "EZU",
               "GLD", "IAU", "TLT", "IEF", "SHY", "BIL", "VNQ", "SMH", "SOXX", "XLK", "XLV", "XLU", "XLP",
               "XLE", "XLF", "XLB", "XLI", "XLY", "QUAL", "MTUM", "USMV", "RSP", "ARKK", "VTV", "VUG", "SCHD"],
    # longer-history mutual funds / indices (dot-com bubble build-up and earlier)
    "long": ["VFINX", "FSELX", "VUSTX", "VFITX", "VGTSX", "VEIEX", "^NDX", "^IXIC", "^SOX", "^GSPC", "^VIX",
             "^TNX", "^IRX", "GC=F"],
    # Phase 2 candidates: mid-cap growth / mid caps, quality since 2005, low volatility, software, equal weight
    "phase2": ["IWP", "IJK", "MDY", "SPHQ", "SPLV", "IGV", "XSD", "RSP", "QQQE", "VBK"],
    "fx": ["EURUSD=X"],
    "stocks": ["NVDA", "MSFT", "AAPL", "GOOGL", "AMZN", "META", "AVGO", "TSM", "AMD", "ASML", "MU", "ORCL",
               "PLTR", "TSLA", "NFLX", "LLY", "NVO", "JPM", "V", "MA", "COST", "BRK-B", "UNH", "SAP"],
    # UCITS ETFs / ETCs on European exchanges (euro or other listing currency), for tracking checks
    "ucits": ["VWCE.DE", "EUNL.DE", "IWDA.AS", "SXR8.DE", "VUAA.DE", "CSPX.L", "CNDX.L", "EQQQ.DE", "SXRV.DE",
              "VVSM.DE", "SEC0.DE", "ZPRV.DE", "IS3N.DE", "XEON.DE", "4GLD.DE", "SGLD.L", "IGLN.L", "EUNA.DE",
              "IUSQ.DE", "SPYI.DE", "IS3Q.DE", "IS3R.DE", "XDWT.DE", "QDVE.DE", "XAIX.DE", "EXXT.DE", "SXRT.DE",
              "EXSA.DE", "MEUD.PA", "VGEA.DE", "IBGS.AS", "XGLE.DE", "EUNH.DE", "IS0E.DE", "PPFB.DE", "WTAI.L",
              "SXRM.DE", "SXRS.DE", "QDVW.DE"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    frames, log = [], {}
    for g, tks in GROUPS.items():
        for attempt in range(3):
            try:
                df = yf.download(tks, period="max", auto_adjust=True, progress=False, threads=True, group_by="column")
                break
            except Exception as e:                                   # noqa: BLE001 - logged, retried
                log[f"{g}_error_{attempt}"] = repr(e)
                time.sleep(10 * (attempt + 1))
        else:
            continue
        close = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(columns={"Close": tks[0]})
        for t in tks:
            s = close[t].dropna() if t in close else pd.Series(dtype=float)
            log[t] = {"first": str(s.index[0].date()) if len(s) else None, "last": str(s.index[-1].date()) if len(s) else None,
                      "n": int(len(s))}
        frames.append(close)
        time.sleep(3)
    px = pd.concat(frames, axis=1).sort_index()
    px.index = pd.to_datetime(px.index).tz_localize(None) if getattr(px.index, "tz", None) else pd.to_datetime(px.index)
    px.to_csv(out / "adj_close.csv")
    (out / "fetch_log.json").write_text(json.dumps(log, indent=1))
    missing = [t for t, v in log.items() if isinstance(v, dict) and not v["n"]]
    print("rows", len(px), "cols", px.shape[1], "missing", missing)


if __name__ == "__main__":
    main()
