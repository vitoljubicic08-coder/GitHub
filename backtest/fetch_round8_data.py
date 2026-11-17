#!/usr/bin/env python3
"""Download the outside data used by round 8 (SHORTLIST_8.md) into a local folder.

  squeezemetrics.com/monitor/static/DIX.csv   SqueezeMetrics DIX and GEX (dealer gamma estimate), daily
  Yahoo Finance ^VIX, ^VIX3M (yfinance)       CBOE volatility indices, daily close
  federalreserve.gov FOMC calendars           statement release dates -> data_round8/fomc_statement_dates.csv

The third-party files (DIX, VIX) are kept outside the repository (their terms may not allow
redistribution); the FOMC dates (US government, public) are committed.
CPI release dates were not available: www.bls.gov refuses automated downloads.

  python3 backtest/fetch_round8_data.py --out <folder>
"""
import argparse
import re
import urllib.request
from pathlib import Path

FED = "https://www.federalreserve.gov/monetarypolicy/"


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nb3-research"}), timeout=60) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "DIX.csv").write_bytes(get("https://squeezemetrics.com/monitor/static/DIX.csv"))
    import yfinance as yf
    for t in ("^VIX", "^VIX3M"):
        df = yf.download(t, start="2015-06-01", interval="1d", progress=False, auto_adjust=False)
        if df.columns.nlevels > 1:
            df = df.droplevel(1, axis=1)
        df[["Close"]].to_csv(out / (t.strip("^") + ".csv"))
    dates = set()
    pages = ["fomccalendars.htm"] + [f"fomchistorical{y}.htm" for y in range(2016, 2021)]
    for p in pages:
        dates |= set(re.findall(r"monetary(20\d{6})a\.htm", get(FED + p).decode("utf-8", "ignore")))
    d = sorted(x for x in dates if "20160101" <= x <= "20261231")
    target = Path(__file__).resolve().parent / "data_round8" / "fomc_statement_dates.csv"
    target.write_text("date\n" + "\n".join(d) + "\n")
    print(f"DIX/GEX, VIX, VIX3M -> {out}; {len(d)} FOMC statement dates -> {target}")


if __name__ == "__main__":
    main()
