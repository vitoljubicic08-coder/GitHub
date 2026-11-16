#!/usr/bin/env python3
"""Download multi-year input data for backtest/sip_orb_backtest.py from Massive (formerly Polygon.io).

Authentication: the API key is sent as "Authorization: Bearer <key>". Set MASSIVE_API_KEY, or run
where a proxy injects the header (then MASSIVE_API_KEY can be any placeholder).

Per symbol, 5-minute split-adjusted aggregates are requested in one-year chunks (2 requests for
2 years). From them the script writes:
  <out>/intraday/<SYM>.csv  regular-session bars only (09:30-15:55 New York bar open times)
  <out>/daily/<SYM>.csv     daily bars built from the same data: regular-session open/high/low/close
                            and full-day volume (all sessions), like the exchange's daily bar
Symbols that are already downloaded are skipped, so an interrupted run can be resumed.

Usage:
  python3 backtest/fetch_massive_data.py --symbols-file symbols.txt --start 2024-11-18 \
      --end 2026-11-13 --out data_massive --calls-per-minute 5
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
BASE = "https://api.massive.com"


class RateLimiter:
    def __init__(self, calls_per_minute: float):
        self.interval = 60.0 / calls_per_minute
        self.last = 0.0

    def wait(self) -> None:
        delay = self.last + self.interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self.last = time.monotonic()


def get_json(url: str, limiter: RateLimiter, key: str) -> dict:
    for attempt in range(6):
        limiter.wait()
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or exc.code >= 500:
                time.sleep(min(60 * (attempt + 1), 300))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(30 * (attempt + 1))
    raise RuntimeError(f"giving up after retries: {url.split('?')[0]}")


def fetch_bars(sym: str, start: date, end: date, limiter: RateLimiter, key: str) -> list[dict]:
    bars: list[dict] = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(end, chunk_start + timedelta(days=364))
        url = (f"{BASE}/v2/aggs/ticker/{urllib.parse.quote(sym)}/range/5/minute/"
               f"{chunk_start.isoformat()}/{chunk_end.isoformat()}?adjusted=true&sort=asc&limit=50000")
        while url:
            data = get_json(url, limiter, key)
            if data.get("status") == "ERROR":
                raise RuntimeError(data.get("error", "API error"))
            bars += data.get("results") or []
            url = data.get("next_url")
        chunk_start = chunk_end + timedelta(days=1)
    return bars


def write_symbol(sym: str, bars: list[dict], out: Path) -> int:
    """Write regular-session 5-minute bars and derived daily bars; returns the regular bar count."""
    seen: set[int] = set()
    regular: list[tuple] = []
    daily: OrderedDict[date, dict] = OrderedDict()
    for b in sorted(bars, key=lambda x: x["t"]):
        if b["t"] in seen:
            continue
        seen.add(b["t"])
        t = datetime.fromtimestamp(b["t"] / 1000, tz=timezone.utc).astimezone(NY)
        if t.weekday() > 4:
            continue
        d = t.date()
        day = daily.setdefault(d, {"o": None, "h": None, "l": None, "c": None, "v": 0.0})
        day["v"] += float(b.get("v") or 0.0)
        mod = t.hour * 60 + t.minute
        if 570 <= mod < 960:
            o, h, l, c, v = b["o"], b["h"], b["l"], b["c"], b.get("v") or 0.0
            regular.append((t.isoformat(), o, h, l, c, v))
            day["o"] = o if day["o"] is None else day["o"]
            day["h"] = h if day["h"] is None else max(day["h"], h)
            day["l"] = l if day["l"] is None else min(day["l"], l)
            day["c"] = c
    if not regular:
        return 0
    tmp_i, tmp_d = out / "intraday" / f".{sym}.tmp", out / "daily" / f".{sym}.tmp"
    with tmp_i.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume", "is_market"])
        for row in regular:
            w.writerow([*row, 1])
    with tmp_d.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for d, x in daily.items():
            if x["o"] is not None:
                w.writerow([d.isoformat(), x["o"], x["h"], x["l"], x["c"], x["v"]])
    tmp_d.replace(out / "daily" / f"{sym}.csv")
    tmp_i.replace(out / "intraday" / f"{sym}.csv")
    return len(regular)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols-file", type=Path, required=True, help="one ticker per line")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--calls-per-minute", type=float, default=5.0, help="5 on the free plan")
    args = parser.parse_args(argv)

    key = os.environ.get("MASSIVE_API_KEY", "proxy-injected")
    symbols = [s.strip().upper() for s in args.symbols_file.read_text().split() if s.strip()]
    (args.out / "intraday").mkdir(parents=True, exist_ok=True)
    (args.out / "daily").mkdir(parents=True, exist_ok=True)
    limiter = RateLimiter(args.calls_per_minute)
    done = skipped = failed = 0
    for n, sym in enumerate(symbols, 1):
        if (args.out / "intraday" / f"{sym}.csv").exists():
            skipped += 1
            continue
        try:
            count = write_symbol(sym, fetch_bars(sym, args.start, args.end, limiter, key), args.out)
            done += count > 0
        except Exception as exc:  # one bad symbol must not stop the run
            failed += 1
            print(f"{sym}: failed ({exc})", file=sys.stderr, flush=True)
        if n % 25 == 0 or n == len(symbols):
            print(f"progress {n}/{len(symbols)} saved {done} skipped {skipped} failed {failed}", flush=True)
    print(f"finished: saved {done}, skipped {skipped}, failed {failed}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
