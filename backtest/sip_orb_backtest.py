#!/usr/bin/env python3
"""SIP-ORB Precision V1 - offline backtest harness.

Replays 5-minute bars through the reference signal engine (a statement-by-
statement mirror of the Pine engine, tests/sip_orb_reference_engine.py) and a
broker emulator that follows the Pine strategy (sections S1-S4) and
TradingView's default fill model:

  * orders submitted at a bar's close fill at the NEXT bar's open;
  * the stop is fill price -/+ 10% of the previous daily ATR(14); it fills at
    the stop price, or at the bar open when the bar gaps through it;
  * 2 ticks of adverse slippage on every fill, 0.005 USD/share per side;
  * end-of-day close submitted on the 15:50 bar (fills at the 15:55 open),
    with the same failsafes as the Pine strategy.

Each symbol is an independent 10,000 USD account, as in TradingView's Strategy
Tester. These are NOT TradingView results: the data feed, bar construction
and intrabar fill details can differ.

Input layout (CSV files with a header row):
  <data>/intraday/<SYMBOL>.csv  time,open,high,low,close,volume[,is_market]
      time = ISO-8601 bar OPEN time with UTC offset, e.g. 2026-09-01T09:30:00-04:00
      is_market (1/0) is optional; without it every bar is treated as regular-session
      (the engine still ignores bars outside 09:30-16:00 New York time).
  <data>/daily/<SYMBOL>.csv     date,open,high,low,close,volume   (date = YYYY-MM-DD)

Usage:
  python3 backtest/sip_orb_backtest.py --data data --out backtest/results --min-trades 1000
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from sip_orb_reference_engine import (  # noqa: E402
    LOOKBACK, OPEN_MOD, SESSION_END_MOD, SLIPPAGE_TICKS, STOP_ATR_FRACTION, TZ,
    Bar, SipOrbEngine, position_size,
)

INITIAL_CAPITAL = 10_000.0
COMMISSION_PER_SHARE = 0.005
EOD_SUBMIT_MOD = 950          # 15:50 New York
BAR_MINUTES = 5


def mintick(price: float) -> float:
    """US equity tick size (Reg NMS): 0.01 at or above 1 USD, 0.0001 below."""
    return 0.01 if price >= 1.0 else 0.0001


# ----------------------------------------------------------------------------
# Daily reference values: request.security("D", [ta.atr(14)[1], math.sum(volume, 14)[1]], lookahead_on)
# ----------------------------------------------------------------------------
class DailyReference:
    """ATR(14) (Wilder RMA seeded with an SMA, as ta.atr) and the 14-day volume sum."""

    def __init__(self, rows: list[tuple[date, float, float, float, float, float | None]]):
        self.dates: list[date] = []
        self.values: list[tuple[float | None, float | None]] = []
        trs: list[float] = []
        vols: list[float | None] = []
        atr: float | None = None
        prev_close: float | None = None
        for d, _o, h, l, c, v in sorted(rows):
            tr = h - l if prev_close is None else max(h - l, abs(h - prev_close), abs(l - prev_close))
            trs.append(tr)
            if atr is None:
                if len(trs) == LOOKBACK:
                    atr = sum(trs) / LOOKBACK
            else:
                atr = (atr * (LOOKBACK - 1) + tr) / LOOKBACK
            vols.append(v)
            window = vols[-LOOKBACK:]
            vol_sum = sum(window) if len(window) == LOOKBACK and None not in window else None
            self.dates.append(d)
            self.values.append((atr, vol_sum))
            prev_close = c

    def previous(self, d: date) -> tuple[float | None, float | None]:
        """Values of the last COMPLETED daily bar strictly before date d."""
        i = bisect.bisect_left(self.dates, d)
        return self.values[i - 1] if i > 0 else (None, None)


# ----------------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------------
RawBar = tuple[datetime, float | None, float | None, float | None, float | None, float | None, bool]


def _num(text: str | None) -> float | None:
    if text is None or text.strip() == "" or text.strip().lower() == "nan":
        return None
    value = float(text)
    return None if math.isnan(value) else value


def load_intraday(path: Path) -> list[RawBar]:
    by_time: dict[datetime, RawBar] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            t = datetime.fromisoformat(row["time"])
            if t.tzinfo is None:
                raise ValueError(f"{path}: time must carry a UTC offset: {row['time']}")
            is_market = row.get("is_market", "1").strip().lower() not in ("0", "false")
            by_time[t] = (t, _num(row["open"]), _num(row["high"]), _num(row["low"]),
                          _num(row["close"]), _num(row["volume"]), is_market)
    return [by_time[t] for t in sorted(by_time)]


def load_daily(path: Path) -> DailyReference:
    rows = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            o, h, l, c = (_num(row[k]) for k in ("open", "high", "low", "close"))
            if None in (o, h, l, c):
                continue
            rows.append((date.fromisoformat(row["date"][:10]), o, h, l, c, _num(row["volume"])))
    return DailyReference(rows)


# ----------------------------------------------------------------------------
# Broker emulator (Pine strategy S1-S4)
# ----------------------------------------------------------------------------
@dataclass
class Trade:
    symbol: str
    side: str
    signal_bar_time: str        # open time of the bar carrying the arrow (TradingView bar time)
    signal_close: float
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    exit_reason: str
    qty: int
    stop_distance: float
    stop_price: float
    equity_before: float
    gross_pnl: float
    commission: float
    net_pnl: float
    planned_risk: float
    r_multiple: float
    return_pct: float
    entry_notional_pct: float


@dataclass
class _Position:
    side: int
    qty: int
    entry_time: datetime
    entry_price: float
    stop_price: float
    stop_distance: float
    signal_time: datetime
    signal_close: float
    equity_before: float
    date_key: int


def _ny(t: datetime) -> tuple[date, int, bool]:
    ny = t.astimezone(TZ)
    return ny.date(), ny.hour * 60 + ny.minute, ny.weekday() <= 4


def simulate_symbol(symbol: str, bars: list[RawBar], daily: DailyReference) -> tuple[list[Trade], float, int]:
    """Run one independent account. Returns (closed trades, final equity, trades left open)."""
    engine = SipOrbEngine()
    equity = INITIAL_CAPITAL
    pos: _Position | None = None
    pending_entry: tuple | None = None
    pending_close: str | None = None
    trades: list[Trade] = []

    info = []
    for t, *_rest, is_market in bars:
        d, mod, weekday = _ny(t)
        info.append((d, mod, is_market and weekday and OPEN_MOD <= mod < SESSION_END_MOD))
    # session.islastbar_regular: last regular bar of each New York date in the data.
    last_regular = [False] * len(bars)
    seen: set[date] = set()
    for i in range(len(bars) - 1, -1, -1):
        d, _mod, in_regular = info[i]
        if in_regular and d not in seen:
            last_regular[i] = True
            seen.add(d)

    def close_position(when: datetime, raw_price: float, reason: str) -> None:
        nonlocal equity, pos
        fill = raw_price - pos.side * SLIPPAGE_TICKS * mintick(raw_price)
        gross = pos.side * (fill - pos.entry_price) * pos.qty
        commission = 2 * COMMISSION_PER_SHARE * pos.qty
        net = gross - commission
        planned = pos.qty * pos.stop_distance
        trades.append(Trade(
            symbol=symbol, side="LONG" if pos.side == 1 else "SHORT",
            signal_bar_time=pos.signal_time.isoformat(), signal_close=pos.signal_close,
            entry_time=pos.entry_time.isoformat(), entry_price=round(pos.entry_price, 6),
            exit_time=when.isoformat(), exit_price=round(fill, 6), exit_reason=reason,
            qty=pos.qty, stop_distance=round(pos.stop_distance, 6), stop_price=round(pos.stop_price, 6),
            equity_before=round(pos.equity_before, 2), gross_pnl=round(gross, 4),
            commission=round(commission, 4), net_pnl=round(net, 4), planned_risk=round(planned, 4),
            r_multiple=net / planned if planned > 0 else float("nan"),
            return_pct=100.0 * net / pos.equity_before,
            entry_notional_pct=100.0 * pos.qty * pos.entry_price / pos.equity_before,
        ))
        equity += net
        pos = None

    for i, (t, o, h, l, c, v, is_market) in enumerate(bars):
        d, mod, in_regular = info[i]
        valid_ohlc = None not in (o, h, l, c)

        # 1) Orders submitted at the previous close execute at this bar's open.
        if valid_ohlc:
            if pending_close is not None and pos is not None:
                close_position(t, o, pending_close)
            pending_close = None
            if pending_entry is not None and pos is None:
                side, qty, dist, sig_t, sig_c, eq_before, date_key = pending_entry
                fill = o + side * SLIPPAGE_TICKS * mintick(o)
                pos = _Position(side, qty, t, fill, fill - side * dist, dist, sig_t, sig_c, eq_before, date_key)
            pending_entry = None

            # 2) Stop order inside the bar (gap through the stop fills at the open).
            if pos is not None:
                if pos.side == 1:
                    if o <= pos.stop_price:
                        close_position(t, o, "Stop (gap)")
                    elif l <= pos.stop_price:
                        close_position(t, pos.stop_price, "Stop")
                else:
                    if o >= pos.stop_price:
                        close_position(t, o, "Stop (gap)")
                    elif h >= pos.stop_price:
                        close_position(t, pos.stop_price, "Stop")

        # 3) Signal engine on the confirmed bar.
        prev_atr, prev_vol_sum = daily.previous(d)
        buy, sell = engine.update(Bar(t, o, h, l, c, v, prev_atr, prev_vol_sum, is_market=is_market))
        if not valid_ohlc:
            continue

        # 4) Strategy logic at the bar close (S3 exits, then S4 entries).
        bar_close_time = t + timedelta(minutes=BAR_MINUTES)
        if pos is not None:
            held_from_prior = pos.date_key != engine.sess_date_key
            is_eod_submit_bar = in_regular and EOD_SUBMIT_MOD <= mod < EOD_SUBMIT_MOD + BAR_MINUTES
            if is_eod_submit_bar and not held_from_prior:
                pending_close = "EOD 15:55"
            elif held_from_prior or not in_regular or mod >= EOD_SUBMIT_MOD + BAR_MINUTES or last_regular[i]:
                close_position(bar_close_time, c, "EOD failsafe")

        if (buy or sell) and pos is None:
            qty = position_size(equity, engine.sess_prev_atr, c, mintick(c))
            if equity > 0 and qty >= 1:
                pending_entry = (1 if buy else -1, qty, engine.sess_prev_atr * STOP_ATR_FRACTION,
                                 t, c, equity, engine.sess_date_key)

    return trades, equity, 1 if pos is not None else 0


# ----------------------------------------------------------------------------
# Statistics
# ----------------------------------------------------------------------------
def max_drawdown(values: list[float]) -> float:
    peak, worst, running = 0.0, 0.0, 0.0
    for x in values:
        running += x
        peak = max(peak, running)
        worst = min(worst, running - peak)
    return worst


def summarize(trades: list[Trade], final_equity: dict[str, float]) -> dict:
    if not trades:
        return {"trades": 0}
    ordered = sorted(trades, key=lambda tr: tr.exit_time)
    r = [tr.r_multiple for tr in ordered]
    net = [tr.net_pnl for tr in ordered]
    wins = [x for x in net if x > 0]
    losses = [x for x in net if x <= 0]

    def side_stats(side: str) -> dict:
        sub = [tr for tr in ordered if tr.side == side]
        if not sub:
            return {"trades": 0}
        return {"trades": len(sub),
                "win_rate_pct": 100.0 * sum(tr.net_pnl > 0 for tr in sub) / len(sub),
                "avg_r": statistics.fmean(tr.r_multiple for tr in sub),
                "net_pnl": sum(tr.net_pnl for tr in sub)}

    streak = longest = 0
    for x in net:
        streak = streak + 1 if x <= 0 else 0
        longest = max(longest, streak)

    reasons: dict[str, int] = {}
    for tr in ordered:
        reasons[tr.exit_reason] = reasons.get(tr.exit_reason, 0) + 1

    equities = list(final_equity.values())
    return {
        "trades": len(ordered),
        "symbols_traded": len({tr.symbol for tr in ordered}),
        "symbols_simulated": len(final_equity),
        "first_entry": min(tr.entry_time for tr in ordered),
        "last_exit": max(tr.exit_time for tr in ordered),
        "win_rate_pct": 100.0 * len(wins) / len(ordered),
        "avg_r": statistics.fmean(r),
        "median_r": statistics.median(r),
        "best_r": max(r),
        "worst_r": min(r),
        "sum_r": sum(r),
        "max_drawdown_r": max_drawdown(r),
        "profit_factor": (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None,
        "net_pnl_usd": sum(net),
        "commission_usd": sum(tr.commission for tr in ordered),
        "avg_net_pnl_usd": statistics.fmean(net),
        "avg_return_pct_of_equity": statistics.fmean(tr.return_pct for tr in ordered),
        "avg_entry_notional_pct": statistics.fmean(tr.entry_notional_pct for tr in ordered),
        "entries_above_100pct_notional": sum(tr.entry_notional_pct > 100.0 for tr in ordered),
        "longest_losing_streak": longest,
        "exit_reasons": reasons,
        "long": side_stats("LONG"),
        "short": side_stats("SHORT"),
        "accounts_profitable_pct": 100.0 * sum(e > INITIAL_CAPITAL for e in equities) / len(equities),
        "avg_account_return_pct": statistics.fmean(100.0 * (e / INITIAL_CAPITAL - 1) for e in equities),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, required=True, help="folder with intraday/ and daily/ CSVs")
    parser.add_argument("--out", type=Path, required=True, help="folder for trades.csv and summary.json")
    parser.add_argument("--min-trades", type=int, default=1000, help="warn when fewer trades are produced")
    args = parser.parse_args(argv)

    intraday_dir, daily_dir = args.data / "intraday", args.data / "daily"
    symbols = sorted(p.stem for p in intraday_dir.glob("*.csv") if (daily_dir / p.name).exists())
    if not symbols:
        print(f"No symbol has both {intraday_dir}/<SYM>.csv and {daily_dir}/<SYM>.csv", file=sys.stderr)
        return 2

    all_trades: list[Trade] = []
    final_equity: dict[str, float] = {}
    still_open = 0
    for sym in symbols:
        trades, equity, open_count = simulate_symbol(sym, load_intraday(intraday_dir / f"{sym}.csv"),
                                                     load_daily(daily_dir / f"{sym}.csv"))
        all_trades += trades
        final_equity[sym] = equity
        still_open += open_count

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "trades.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(Trade.__dataclass_fields__))
        writer.writeheader()
        for tr in sorted(all_trades, key=lambda x: x.entry_time):
            writer.writerow(asdict(tr))
    summary = summarize(all_trades, final_equity)
    summary["trades_left_open_at_end_of_data"] = still_open
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    print(json.dumps(summary, indent=2, default=str))
    if summary["trades"] < args.min_trades:
        print(f"WARNING: only {summary['trades']} trades (< {args.min_trades}). Add symbols or history.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
