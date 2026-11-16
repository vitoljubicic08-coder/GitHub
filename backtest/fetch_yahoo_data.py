#!/usr/bin/env python3
"""Download input data for backtest/sip_orb_backtest.py from Yahoo Finance.

Requires:  pip install yfinance pandas
NOTE: this script was written but NOT executed during development, because
package installation and market-data downloads were blocked in that
environment. Check its output before relying on it.

Steps
  1. Universe: NASDAQ Trader symbol directories (every NASDAQ, NYSE and NYSE
     American listing). Keeps common stocks only: no ETFs, test issues,
     warrants, units, rights, preferreds, notes, funds or depositary shares
     (ADRs), matching the Pine script's syminfo.type == "stock" rule.
  2. Loose daily pre-filter, so that the engine's exact daily filters decide:
     at some point in the last 6 months, a close above --min-price and a 20-day
     average volume above --min-avg-volume.
  3. For the survivors: 1 year of daily bars and the last 60 days of
     regular-session 5-minute bars (Yahoo's limit for 5-minute history).

Output: <out>/intraday/<SYM>.csv and <out>/daily/<SYM>.csv, as expected by
sip_orb_backtest.py.

Caveats: the universe holds only currently listed symbols, so delisted stocks
are missing (survivorship bias). Yahoo volumes can differ from TradingView's
feed. 60 days is a single short market regime.

Usage:
  python3 backtest/fetch_yahoo_data.py --out data
  python3 backtest/sip_orb_backtest.py --data data --out backtest/results --min-trades 1000
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.request
from pathlib import Path

NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/SymbolDirectory/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/SymbolDirectory/otherlisted.txt"
OTHER_EXCHANGES = {"N", "A"}   # N = NYSE, A = NYSE American
EXCLUDED_NAME = re.compile(
    r"\b(warrants?|units?|rights?|preferred|depositary|notes?|debentures?|fund|etn|subordinated)\b", re.I)


def load_universe() -> list[str]:
    symbols: set[str] = set()
    for url, symbol_col in ((NASDAQ_LISTED, "Symbol"), (OTHER_LISTED, "ACT Symbol")):
        text = urllib.request.urlopen(url, timeout=60).read().decode("latin-1")
        lines = [ln for ln in text.splitlines() if ln and not ln.startswith("File Creation Time")]
        for row in csv.DictReader(lines, delimiter="|"):
            if row.get("Test Issue") != "N" or row.get("ETF") != "N":
                continue
            if url == OTHER_LISTED and row.get("Exchange") not in OTHER_EXCHANGES:
                continue
            if EXCLUDED_NAME.search(row.get("Security Name", "")):
                continue
            sym = (row.get(symbol_col) or "").strip()
            if not sym or any(ch in sym for ch in "$^=+"):
                continue
            symbols.add(sym.replace(".", "-"))     # Yahoo uses BRK-B for BRK.B
    return sorted(symbols)


def prefilter(symbols: list[str], min_price: float, min_avg_volume: float, batch: int) -> list[str]:
    import pandas as pd
    import yfinance as yf

    keep: list[str] = []
    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        df = yf.download(chunk, period="6mo", interval="1d", group_by="ticker",
                         auto_adjust=False, threads=True, progress=False)
        for sym in chunk:
            try:
                sub = df[sym] if isinstance(df.columns, pd.MultiIndex) else df
            except KeyError:
                continue
            sub = sub.dropna(how="all")
            if sub.empty or "Close" not in sub or "Volume" not in sub:
                continue
            avg_volume = sub["Volume"].rolling(20).mean()
            if (sub["Close"] > min_price).any() and (avg_volume > min_avg_volume).any():
                keep.append(sym)
        print(f"pre-filter {min(i + batch, len(symbols))}/{len(symbols)}: kept {len(keep)}", file=sys.stderr)
    return keep


def save_symbol(sym: str, out: Path) -> bool:
    import pandas as pd
    import yfinance as yf

    ticker = yf.Ticker(sym)
    intraday = ticker.history(period="60d", interval="5m", prepost=False, auto_adjust=False)
    daily = ticker.history(period="1y", interval="1d", auto_adjust=False)
    if intraday.empty or daily.empty:
        return False

    def cell(x):
        return "" if pd.isna(x) else x

    with (out / "intraday" / f"{sym}.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume", "is_market"])
        for ts, r in intraday.iterrows():
            w.writerow([ts.isoformat(), cell(r["Open"]), cell(r["High"]), cell(r["Low"]),
                        cell(r["Close"]), cell(r["Volume"]), 1])
    with (out / "daily" / f"{sym}.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for ts, r in daily.iterrows():
            w.writerow([ts.date().isoformat(), cell(r["Open"]), cell(r["High"]), cell(r["Low"]),
                        cell(r["Close"]), cell(r["Volume"])])
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--symbols-file", type=Path, help="one Yahoo symbol per line (skips steps 1-2)")
    parser.add_argument("--min-price", type=float, default=4.0)
    parser.add_argument("--min-avg-volume", type=float, default=500_000)
    parser.add_argument("--batch", type=int, default=200)
    parser.add_argument("--sleep", type=float, default=0.3, help="pause between symbols (rate limiting)")
    args = parser.parse_args(argv)

    if args.symbols_file:
        symbols = [s.strip() for s in args.symbols_file.read_text().split() if s.strip()]
    else:
        universe = load_universe()
        print(f"universe: {len(universe)} common-stock listings", file=sys.stderr)
        symbols = prefilter(universe, args.min_price, args.min_avg_volume, args.batch)

    (args.out / "intraday").mkdir(parents=True, exist_ok=True)
    (args.out / "daily").mkdir(parents=True, exist_ok=True)
    saved = 0
    for n, sym in enumerate(symbols, 1):
        try:
            saved += save_symbol(sym, args.out)
        except Exception as exc:  # one bad symbol must not stop the download
            print(f"{sym}: skipped ({exc})", file=sys.stderr)
        if n % 50 == 0:
            print(f"downloaded {n}/{len(symbols)} (saved {saved})", file=sys.stderr)
        time.sleep(args.sleep)
    print(f"saved {saved} symbols to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
