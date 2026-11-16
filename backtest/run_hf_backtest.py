#!/usr/bin/env python3
"""Multi-year SIP-ORB V1 backtest on a public 1-minute US stock dataset (no account needed).

Data: Hugging Face dataset "Rrishab/OHLCV-1m" (monthly Parquet files of 1-minute bars for
thousands of US tickers, sourced by its author from Finnhub; license not verified). Its prices
are NOT split-adjusted, so splits from Yahoo Finance are applied the way TradingView does it:
prices before a split are divided by the ratio and volumes multiplied by it.

Per month the script builds, for every stock in the universe:
  * regular-session 5-minute bars (09:30-15:55 bar open times) from the 1-minute bars, and
  * a daily bar: regular-session high/low/close and full-day (all sessions) volume,
then feeds them, in date order, into one SymbolSimulator (signal engine + broker emulator) per
stock. State carries across months, so each stock is one continuous $10,000 account.

Exact shortcut: after a stock's first regular bar of a day, if the engine has marked the session
ineligible (filters failed, no 09:30 bar, doji, RVOL < 2) and the account is flat with no pending
orders, the rest of that day cannot change anything, so those bars are skipped.

Universe: current US common stocks from the NASDAQ Trader directories (fetch_yahoo_data.py).
Delisted stocks are therefore missing (survivorship bias), and a renamed stock only has history
under its current ticker.

Usage:
  python3 backtest/run_hf_backtest.py --start 2023-03 --end 2026-03 --cache /tmp/hf --out results_hf
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_yahoo_data import load_universe  # noqa: E402
from sip_orb_backtest import DailyAccumulator, SymbolSimulator, Trade, summarize  # noqa: E402

DATASET_URL = "https://huggingface.co/datasets/Rrishab/OHLCV-1m/resolve/main/data/ohlcv_{ym}.parquet"
NY = ZoneInfo("America/New_York")


def months(start: str, end: str) -> list[str]:
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def download(url: str, path: Path) -> None:
    tmp = path.with_suffix(".part")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=600) as resp, tmp.open("wb") as f:
                while chunk := resp.read(1 << 20):
                    f.write(chunk)
            tmp.replace(path)
            return
        except OSError as exc:
            print(f"  download retry {attempt + 1}: {exc}", flush=True)
            time.sleep(15 * (attempt + 1))
    raise RuntimeError(f"download failed: {url}")


def load_splits(yahoo_symbols: list[str], start: str, cache: Path) -> dict[str, list[tuple[int, float]]]:
    """{dataset_ticker: [(ex_date_yyyymmdd, ratio), ...]} from Yahoo's split history."""
    if cache.exists():
        return {k: [tuple(x) for x in v] for k, v in json.loads(cache.read_text()).items()}
    import yfinance as yf

    out: dict[str, list[tuple[int, float]]] = {}
    for i in range(0, len(yahoo_symbols), 200):
        chunk = yahoo_symbols[i:i + 200]
        df = yf.download(chunk, start=f"{start}-01", interval="1d", actions=True, group_by="ticker",
                         auto_adjust=False, progress=False, threads=True)
        for sym in chunk:
            try:
                sub = df[sym] if isinstance(df.columns, pd.MultiIndex) else df
            except KeyError:
                continue
            if "Stock Splits" not in sub:
                continue
            sp = sub["Stock Splits"].dropna()
            sp = sp[sp > 0]
            if len(sp):
                out[sym.replace("-", ".")] = [(int(ts.strftime("%Y%m%d")), float(r)) for ts, r in sp.items()]
        print(f"  splits {min(i + 200, len(yahoo_symbols))}/{len(yahoo_symbols)}: {len(out)} stocks with splits",
              flush=True)
    cache.write_text(json.dumps(out))
    return out


def build_month(path: Path, tickers: list[str], splits: dict[str, list[tuple[int, float]]]):
    """Return (5-minute regular-session bars, daily bars), both sorted by ticker, date[, bar]."""
    table = pq.read_table(path, columns=["timestamp", "open", "high", "low", "close", "volume", "ticker"],
                          filters=[("ticker", "in", tickers)], read_dictionary=["ticker"])
    df = table.to_pandas()
    if df.empty:
        return None, None
    ny = df["timestamp"].dt.tz_convert(NY)
    df["dkey"] = (ny.dt.year * 10000 + ny.dt.month * 100 + ny.dt.day).astype(np.int64)
    df["mod"] = (ny.dt.hour * 60 + ny.dt.minute).astype(np.int64)
    df = df[ny.dt.weekday < 5]
    df = df.sort_values(["ticker", "timestamp"], kind="stable")

    keys = ["ticker", "dkey"]
    all_volume = df.groupby(keys, sort=True, observed=True)["volume"].sum()
    rth = df[(df["mod"] >= 570) & (df["mod"] < 960)].copy()
    rth["b5"] = (rth["mod"] // 5) * 5
    bars = (rth.groupby(keys + ["b5"], sort=True, observed=True)
               .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                    close=("close", "last"), volume=("volume", "sum"))
               .reset_index())
    daily = (rth.groupby(keys, sort=True, observed=True)
                .agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
                .reset_index())
    daily["volume"] = all_volume.reindex(pd.MultiIndex.from_frame(daily[keys])).to_numpy()

    # TradingView-style split adjustment (all known splits up to today).
    for frame, price_cols in ((bars, ["open", "high", "low", "close"]), (daily, ["high", "low", "close"])):
        tick = frame["ticker"].astype(str).to_numpy()
        factor = np.ones(len(frame))
        for tk in set(np.unique(tick)) & splits.keys():
            rows = tick == tk
            for ex_date, ratio in splits[tk]:
                factor[rows & (frame["dkey"].to_numpy() < ex_date)] *= ratio
        if (factor != 1.0).any():
            for col in price_cols:
                frame[col] = frame[col].to_numpy() / factor
            frame["volume"] = frame["volume"].to_numpy() * factor
    return bars, daily


def _f(x: float) -> float | None:
    return None if x != x else float(x)


def simulate_month(bars: pd.DataFrame, daily: pd.DataFrame, sims: dict[str, SymbolSimulator],
                   accs: dict[str, DailyAccumulator], skip_ineligible: bool = True) -> int:
    tk = bars["ticker"].astype(str).to_numpy()
    dk = bars["dkey"].to_numpy()
    b5 = bars["b5"].to_numpy()
    o, h, l, c, v = (bars[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
    change = np.flatnonzero((tk[1:] != tk[:-1]) | (dk[1:] != dk[:-1])) + 1
    starts = np.concatenate(([0], change))
    ends = np.concatenate((change, [len(tk)]))
    assert len(starts) == len(daily), "bar groups and daily rows are misaligned"
    dh, dl, dc, dv = (daily[k].to_numpy() for k in ("high", "low", "close", "volume"))
    processed = 0
    for g, (s, e) in enumerate(zip(starts, ends)):
        ticker, dkey = tk[s], int(dk[s])
        sim = sims.get(ticker)
        if sim is None:
            sim = sims[ticker] = SymbolSimulator(ticker)
            accs[ticker] = DailyAccumulator()
        acc = accs[ticker]
        prev_atr, prev_vol_sum = acc.values
        y, mo, da = dkey // 10000, dkey // 100 % 100, dkey % 100
        for j in range(s, e):
            minutes = int(b5[j])
            t = datetime(y, mo, da, minutes // 60, minutes % 60, tzinfo=NY)
            sim.process((t, _f(o[j]), _f(h[j]), _f(l[j]), _f(c[j]), _f(v[j]), True),
                        prev_atr, prev_vol_sum, j == e - 1)
            processed += 1
            if skip_ineligible and j == s and sim.is_idle() and not sim.engine.sess_eligible:
                break  # the rest of this day cannot produce a signal or a fill
        if dh[g] == dh[g] and dl[g] == dl[g] and dc[g] == dc[g]:
            acc.add(float(dh[g]), float(dl[g]), float(dc[g]), _f(dv[g]))
    return processed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", required=True, help="first month, YYYY-MM")
    parser.add_argument("--end", required=True, help="last month, YYYY-MM")
    parser.add_argument("--cache", type=Path, required=True, help="folder for temporary downloads")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--keep-files", action="store_true", help="keep monthly Parquet files")
    args = parser.parse_args(argv)
    args.cache.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    yahoo_universe = load_universe()
    tickers = sorted({s.replace("-", ".") for s in yahoo_universe})
    print(f"universe: {len(tickers)} current US common stocks", flush=True)
    splits = load_splits(yahoo_universe, args.start, args.cache / "splits.json")
    print(f"splits: {len(splits)} stocks with at least one split since {args.start}", flush=True)

    sims: dict[str, SymbolSimulator] = {}
    accs: dict[str, DailyAccumulator] = {}
    for ym in months(args.start, args.end):
        path = args.cache / f"ohlcv_{ym}.parquet"
        if not path.exists():
            download(DATASET_URL.format(ym=ym), path)
        bars, daily = build_month(path, tickers, splits)
        processed = 0 if bars is None else simulate_month(bars, daily, sims, accs)
        if not args.keep_files:
            path.unlink()
        n_trades = sum(len(s.trades) for s in sims.values())
        n_rows = 0 if bars is None else len(bars)
        print(f"{ym}: 5-min bars {n_rows:>9,} | simulated {processed:>9,} | stocks {len(sims):>5} "
              f"| trades so far {n_trades:>6,} | {time.time() - t0:6.0f}s", flush=True)

    trades = sorted((t for s in sims.values() for t in s.trades), key=lambda t: t.entry_time)
    with (args.out / "trades.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(Trade.__dataclass_fields__))
        writer.writeheader()
        for tr in trades:
            writer.writerow(asdict(tr))
    summary = summarize(trades, {k: s.equity for k, s in sims.items()})
    summary["trades_left_open_at_end_of_data"] = sum(s.pos is not None for s in sims.values())
    summary["data"] = f"Rrishab/OHLCV-1m {args.start}..{args.end}, split-adjusted with Yahoo splits"
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
