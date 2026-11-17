"""Historical 1-minute session data for replay.

Two formats are supported:
  * the research cache used by the verified backtest (`market_*.npz` with arrays `tick`, `dkey`,
    `grid` [n_days, 390, 5 = open/high/low/close/volume] and `prev_close`);
  * a CSV of 1-minute bars with columns `timestamp,open,high,low,close[,volume]`, where timestamp is
    ISO-8601 with a UTC offset (bar OPEN time). Only regular-session minutes 09:30-15:59 New York are
    kept; DST is handled by converting every timestamp to America/New_York.
"""
from __future__ import annotations

import csv
import glob
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

import numpy as np

from nb3bot.timeutil import NY, minute_index

MINUTES = 390


@dataclass
class Session:
    key: int                 # yyyymmdd New York
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray

    def minutes(self) -> Iterator[tuple[int, float, float, float, float, float]]:
        for m in range(MINUTES):
            if not (np.isnan(self.o[m]) and np.isnan(self.h[m]) and np.isnan(self.l[m]) and np.isnan(self.c[m])):
                yield m, float(self.o[m]), float(self.h[m]), float(self.l[m]), float(self.c[m]), float(self.v[m])

    def last_close_at_or_before(self, m: int) -> float:
        seg = self.c[: m + 1]
        ok = ~np.isnan(seg)
        return float(seg[ok][-1]) if ok.any() else float("nan")


def load_npz_cache(cache_dir: str | Path, ticker: str) -> list[Session]:
    keys, grids = [], []
    for path in sorted(glob.glob(str(Path(cache_dir) / "market_*.npz"))):
        z = np.load(path)
        m = z["tick"] == ticker
        keys.append(z["dkey"][m])
        grids.append(z["grid"][m])
    if not keys:
        raise FileNotFoundError(f"no market_*.npz files in {cache_dir}")
    dkey = np.concatenate(keys)
    order = np.argsort(dkey)
    grid = np.concatenate(grids)[order].astype(np.float64)
    dkey = dkey[order]
    return [Session(int(k), g[:, 0].copy(), g[:, 1].copy(), g[:, 2].copy(), g[:, 3].copy(), g[:, 4].copy())
            for k, g in zip(dkey, grid)]


def load_csv(path: str | Path) -> list[Session]:
    days: dict[int, np.ndarray] = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            ts = datetime.fromisoformat(row["timestamp"])
            if ts.tzinfo is None:
                raise ValueError("CSV timestamps must carry a UTC offset (for example 2025-03-10T13:30:00+00:00)")
            ny = ts.astimezone(NY)
            m = minute_index(ny)
            if m is None:
                continue
            key = ny.year * 10000 + ny.month * 100 + ny.day
            g = days.setdefault(key, np.full((MINUTES, 5), np.nan))
            g[m] = [float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]),
                    float(row.get("volume") or 0)]
    return [Session(k, g[:, 0], g[:, 1], g[:, 2], g[:, 3], g[:, 4]) for k, g in sorted(days.items())]


def load_sessions(source: str | Path, ticker: str = "QQQ") -> list[Session]:
    p = Path(source)
    return load_csv(p) if p.suffix.lower() == ".csv" else load_npz_cache(p, ticker)
