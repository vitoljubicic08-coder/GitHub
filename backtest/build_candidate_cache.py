#!/usr/bin/env python3
"""Build a compact research cache of SIP-ORB candidate stock-days from the 1-minute dataset.

One pass over the monthly Parquet files of "Rrishab/OHLCV-1m" (see run_hf_backtest.py). For every
current US common stock it tracks, exactly like the Pine engine, the previous-day ATR(14), the
14-session daily volume sum and the 14-session history of opening 5-minute volumes. A stock-day is
stored as a candidate when it passes the spec's daily filters and has a looser opening RVOL >= 1:
  * opening 5-minute bar exists, its open > 5 USD
  * previous 14-session daily volume sum >= 14,000,000 (mean >= 1,000,000)
  * previous daily ATR(14) > 0.50
  * opening RVOL (vs the 14 previous opening bars) >= 1.0
For each candidate the full regular-session 1-minute path (390 minutes x OHLCV, NaN where no trade)
is stored with features: opening-bar OHLCV, RVOL, previous ATR, previous close, premarket volume.
SPY and QQQ grids are stored for every day as market context. Prices are split-adjusted like
TradingView (Yahoo split history).

Output per month in --out:  cand_YYYY-MM.npz  and  market_YYYY-MM.npz

Usage:
  python3 backtest/build_candidate_cache.py --start 2023-03 --end 2026-03 --download /tmp/hf --out /tmp/cache
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_yahoo_data import load_universe  # noqa: E402
from run_hf_backtest import DATASET_URL, NY, download, load_splits, months  # noqa: E402
from sip_orb_backtest import DailyAccumulator  # noqa: E402

MARKET = ("SPY", "QQQ")
MIN_RVOL = 1.0
LOOKBACK = 14
MINUTES = 390          # 09:30 .. 15:59
META = ("o5", "h5", "l5", "c5", "v5", "rvol", "prev_atr", "prev_vol_sum", "prev_close", "pre_vol")


class _State:
    __slots__ = ("acc", "opens", "prev_close")

    def __init__(self) -> None:
        self.acc = DailyAccumulator()
        self.opens: deque[float] = deque(maxlen=LOOKBACK)
        self.prev_close: float | None = None


def _split_factor(tick: np.ndarray, dkey: np.ndarray, splits: dict) -> np.ndarray:
    factor = np.ones(len(tick))
    for tk in set(np.unique(tick)) & splits.keys():
        rows = tick == tk
        for ex_date, ratio in splits[tk]:
            factor[rows & (dkey < ex_date)] *= ratio
    return factor


def process_month(path: Path, tickers: list[str], splits: dict, states: dict[str, _State]):
    table = pq.read_table(path, columns=["timestamp", "open", "high", "low", "close", "volume", "ticker"],
                          filters=[("ticker", "in", tickers + list(MARKET))], read_dictionary=["ticker"])
    df = table.to_pandas()
    ny = df["timestamp"].dt.tz_convert(NY)
    df["dkey"] = (ny.dt.year * 10000 + ny.dt.month * 100 + ny.dt.day).astype(np.int64)
    df["mod"] = (ny.dt.hour * 60 + ny.dt.minute).astype(np.int64)
    df = df[ny.dt.weekday < 5].sort_values(["ticker", "timestamp"], kind="stable")

    keys = ["ticker", "dkey"]
    rth_df = df[(df["mod"] >= 570) & (df["mod"] < 960)]
    day = rth_df.groupby(keys, sort=True, observed=True).agg(
        d_high=("high", "max"), d_low=("low", "min"), d_close=("close", "last"))
    day = day.join(df.groupby(keys, sort=True, observed=True)["volume"].sum().rename("vol_all"), how="left")
    pre = df[(df["mod"] >= 240) & (df["mod"] < 570)].groupby(keys, sort=True, observed=True)["volume"].sum()
    day = day.join(pre.rename("pre_vol"), how="left")
    o5 = rth_df[rth_df["mod"] < 575].groupby(keys, sort=True, observed=True).agg(
        o5=("open", "first"), h5=("high", "max"), l5=("low", "min"), c5=("close", "last"), v5=("volume", "sum"))
    day = day.join(o5, how="left").reset_index()

    tick = day["ticker"].astype(str).to_numpy()
    dkey = day["dkey"].to_numpy()
    factor = _split_factor(tick, dkey, splits)
    cols = {c: day[c].to_numpy(dtype=float) for c in day.columns if c not in ("ticker", "dkey")}
    for c in ("d_high", "d_low", "d_close", "o5", "h5", "l5", "c5"):
        cols[c] = cols[c] / factor
    for c in ("vol_all", "pre_vol", "v5"):
        cols[c] = cols[c] * factor

    # 1-minute RTH rows, grouped exactly like `day` (ticker category order, then date).
    r_code = rth_df["ticker"].cat.codes.to_numpy()
    r_dk = rth_df["dkey"].to_numpy()
    change = np.flatnonzero((r_code[1:] != r_code[:-1]) | (r_dk[1:] != r_dk[:-1])) + 1
    starts = np.concatenate(([0], change))
    ends = np.concatenate((change, [len(r_code)]))
    assert len(starts) == len(day), "minute groups and day rows are misaligned"
    r_min = (rth_df["mod"].to_numpy() - 570).astype(np.int64)
    r_ohlcv = rth_df[["open", "high", "low", "close", "volume"]].to_numpy(dtype=np.float64)

    def grid(i: int) -> np.ndarray:
        g = np.full((MINUTES, 5), np.nan, dtype=np.float32)
        rows = r_ohlcv[starts[i]:ends[i]].copy()
        rows[:, :4] /= factor[i]
        rows[:, 4] *= factor[i]
        g[r_min[starts[i]:ends[i]]] = rows
        return g

    cand_meta = {k: [] for k in META}
    cand_tick, cand_dkey, cand_grid = [], [], []
    mkt_tick, mkt_dkey, mkt_grid, mkt_prev_close = [], [], [], []
    for i in range(len(day)):
        tk = tick[i]
        st = states.get(tk)
        if st is None:
            st = states[tk] = _State()
        prev_atr, prev_vol_sum = st.acc.values
        v5 = cols["v5"][i]
        has_open = v5 == v5 and v5 > 0 and cols["o5"][i] == cols["o5"][i]

        if tk in MARKET:
            mkt_tick.append(tk)
            mkt_dkey.append(dkey[i])
            mkt_grid.append(grid(i))
            mkt_prev_close.append(np.nan if st.prev_close is None else st.prev_close)
        else:
            rvol = np.nan
            if has_open and len(st.opens) == LOOKBACK:
                hist_sum = sum(st.opens)
                if hist_sum > 0:
                    rvol = v5 / (hist_sum / LOOKBACK)
            if (has_open and cols["o5"][i] > 5.0 and prev_vol_sum is not None
                    and prev_vol_sum >= 1_000_000.0 * LOOKBACK and prev_atr is not None and prev_atr > 0.5
                    and rvol == rvol and rvol >= MIN_RVOL):
                cand_tick.append(tk)
                cand_dkey.append(dkey[i])
                cand_grid.append(grid(i))
                values = {"rvol": rvol, "prev_atr": prev_atr, "prev_vol_sum": prev_vol_sum,
                          "prev_close": np.nan if st.prev_close is None else st.prev_close,
                          "pre_vol": cols["pre_vol"][i]}
                for k in META:
                    cand_meta[k].append(values[k] if k in values else cols[k][i])

        # Update state with today's completed data (the engine's update order).
        if has_open:
            st.opens.append(v5)
        if cols["d_high"][i] == cols["d_high"][i]:
            st.acc.add(cols["d_high"][i], cols["d_low"][i], cols["d_close"][i],
                       None if cols["vol_all"][i] != cols["vol_all"][i] else cols["vol_all"][i])
            st.prev_close = cols["d_close"][i]

    def stack(rows):
        return np.stack(rows) if rows else np.zeros((0, MINUTES, 5), np.float32)

    cand = {"tick": np.array(cand_tick, dtype="U12"), "dkey": np.array(cand_dkey, dtype=np.int64),
            "grid": stack(cand_grid), **{k: np.array(v, dtype=np.float64) for k, v in cand_meta.items()}}
    market = {"tick": np.array(mkt_tick, dtype="U12"), "dkey": np.array(mkt_dkey, dtype=np.int64),
              "grid": stack(mkt_grid), "prev_close": np.array(mkt_prev_close, dtype=np.float64)}
    return cand, market


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--download", type=Path, required=True, help="folder for temporary Parquet downloads")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    args.download.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    universe = load_universe()
    tickers = sorted({s.replace("-", ".") for s in universe})
    splits = load_splits(universe, args.start, args.download / "splits.json")
    print(f"universe {len(tickers)} stocks, {len(splits)} with splits", flush=True)
    states: dict[str, _State] = {}
    for ym in months(args.start, args.end):
        src = args.download / f"ohlcv_{ym}.parquet"
        if not src.exists():
            download(DATASET_URL.format(ym=ym), src)
        cand, market = process_month(src, tickers, splits, states)
        np.savez(args.out / f"cand_{ym}.npz", **cand)
        np.savez(args.out / f"market_{ym}.npz", **market)
        src.unlink()
        print(f"{ym}: candidates {len(cand['tick']):>6,} | market days {len(market['tick']):>3} "
              f"| {time.time() - t0:6.0f}s", flush=True)
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
