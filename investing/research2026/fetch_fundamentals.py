#!/usr/bin/env python3
"""Snapshot company fundamentals and analyst estimates from Yahoo Finance via yfinance.

  python3 -I investing/research2026/fetch_fundamentals.py --out <cache dir>

Writes <out>/fundamentals.json. Values are Yahoo's (trailing twelve months unless named otherwise) as of
the download date; they are third-party data and are not committed.
"""
import argparse
import json
import time
from datetime import date
from pathlib import Path

import yfinance as yf

STOCKS = ["NVDA", "MSFT", "AAPL", "GOOGL", "AMZN", "META", "AVGO", "TSM", "AMD", "ASML", "MU", "ORCL",
          "PLTR", "TSLA", "NFLX", "LLY", "NVO", "JPM", "V", "MA", "COST", "BRK-B", "UNH", "SAP"]
FIELDS = ["shortName", "currency", "currentPrice", "marketCap", "enterpriseValue", "trailingPE", "forwardPE",
          "pegRatio", "trailingPegRatio", "priceToSalesTrailing12Months", "enterpriseToEbitda", "totalRevenue",
          "revenueGrowth", "earningsGrowth", "earningsQuarterlyGrowth", "grossMargins", "operatingMargins",
          "ebitdaMargins", "profitMargins", "freeCashflow", "operatingCashflow", "totalCash", "totalDebt",
          "debtToEquity", "returnOnEquity", "returnOnAssets", "beta", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
          "targetMeanPrice", "targetLowPrice", "targetHighPrice", "recommendationMean", "numberOfAnalystOpinions",
          "trailingEps", "forwardEps", "dividendYield", "sharesOutstanding", "sector", "industry"]


def frame(df):
    try:
        return json.loads(df.to_json(orient="index", date_format="iso")) if df is not None else None
    except Exception:                                                 # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = {"asof": str(date.today()), "stocks": {}}
    for tk in STOCKS:
        rec = {}
        for attempt in range(3):
            try:
                t = yf.Ticker(tk)
                info = t.info
                rec = {k: info.get(k) for k in FIELDS}
                rec["earnings_estimate"] = frame(t.earnings_estimate)
                rec["revenue_estimate"] = frame(t.revenue_estimate)
                rec["growth_estimates"] = frame(t.growth_estimates)
                break
            except Exception as e:                                    # noqa: BLE001 - logged, retried
                rec = {"error": repr(e)}
                time.sleep(8 * (attempt + 1))
        out["stocks"][tk] = rec
        print(tk, rec.get("currentPrice"), rec.get("forwardPE"), rec.get("error", ""), flush=True)
        time.sleep(1.5)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "fundamentals.json").write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
