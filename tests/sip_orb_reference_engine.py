"""Offline reference model of the SIP-ORB Precision V1 Pine signal engine.

This module mirrors sections E1-E6 of the Pine "SIGNAL ENGINE" block (and the
strategy's position-sizing rule) statement by statement, so the specification's
validation tests can be executed without TradingView.

It validates the ALGORITHM only. It does not compile or run the Pine code, and
it cannot reproduce TradingView data-feed behaviour.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

# E1. Fixed parameters (identical to the Pine constants).
TZ = ZoneInfo("America/New_York")
MIN_OPEN_PRICE = 5.0
MIN_AVG_DAILY_VOL = 1_000_000.0
MIN_DAILY_ATR = 0.50
MIN_OPEN_RVOL = 2.0
LOOKBACK = 14
OPEN_MOD = 570            # 09:30
WINDOW_START_MOD = 575    # 09:35 inclusive
WINDOW_END_MOD = 660      # 11:00 exclusive
SESSION_END_MOD = 960     # 16:00 exclusive

# Strategy-only constants (identical to the Pine strategy section S1).
RISK_FRACTION = 0.0025
MAX_NOTIONAL_FRACTION = 1.0
STOP_ATR_FRACTION = 0.10
SLIPPAGE_TICKS = 2
QTY_EPSILON = 1e-9


def _na(value: float | None) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


@dataclass(frozen=True)
class Bar:
    """One 5-minute bar as the Pine script sees it on a single execution."""

    time: datetime                    # bar OPEN time, timezone-aware (Pine `time`)
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    prev_daily_atr: float | None      # request.security("D", ta.atr(14)[1], lookahead_on)
    prev_daily_vol_sum: float | None  # request.security("D", math.sum(volume, 14)[1], lookahead_on)
    is_market: bool = True            # session.ismarket
    confirmed: bool = True            # barstate.isconfirmed


class SipOrbEngine:
    """Mirror of the Pine engine's `var` state and per-bar update (E5/E6)."""

    def __init__(self, setup_is_valid: bool = True) -> None:
        self.setup_is_valid = setup_is_valid           # E2 result
        self.sess_date_key: int | None = None
        self.sess_has_opening = False
        self.sess_direction = 0
        self.sess_eligible = False
        self.sess_signal_locked = False
        self.opening_high: float | None = None
        self.opening_low: float | None = None
        self.opening_open: float | None = None
        self.opening_close: float | None = None
        self.opening_volume: float | None = None
        self.sess_opening_rvol: float | None = None
        self.sess_prev_atr: float | None = None
        self.sess_prev_avg_vol: float | None = None
        self.opening_vol_history: list[float] = []

    def update(self, bar: Bar) -> tuple[bool, bool]:
        """Process one script execution; returns (buySignal, sellSignal)."""
        # E4. New York clock.
        ny = bar.time.astimezone(TZ)
        ny_mod = ny.hour * 60 + ny.minute
        ny_date_key = ny.year * 10000 + ny.month * 100 + ny.day
        is_weekday_ny = ny.weekday() <= 4  # Monday..Friday
        in_regular = bar.is_market and is_weekday_ny and OPEN_MOD <= ny_mod < SESSION_END_MOD

        buy_signal = False
        sell_signal = False

        # E6. Engine (confirmed regular-session bars only).
        if bar.confirmed and in_regular:
            if self.sess_date_key is None or ny_date_key != self.sess_date_key:
                self.sess_date_key = ny_date_key
                self.sess_has_opening = False
                self.sess_direction = 0
                self.sess_eligible = False
                self.sess_signal_locked = False
                self.opening_high = self.opening_low = None
                self.opening_open = self.opening_close = None
                self.opening_volume = None
                self.sess_opening_rvol = None
                self.sess_prev_atr = None
                self.sess_prev_avg_vol = None

                if ny_mod == OPEN_MOD:
                    price_data_valid = (
                        not _na(bar.open) and not _na(bar.high) and not _na(bar.low)
                        and not _na(bar.close) and bar.low > 0 and bar.high >= bar.low
                    )
                    volume_valid = not _na(bar.volume) and bar.volume > 0

                    self.opening_high = bar.high
                    self.opening_low = bar.low
                    self.opening_open = bar.open
                    self.opening_close = bar.close
                    self.opening_volume = bar.volume
                    self.sess_has_opening = price_data_valid and volume_valid
                    if not self.sess_has_opening:
                        self.sess_direction = 0
                    elif self.opening_close > self.opening_open:
                        self.sess_direction = 1
                    elif self.opening_close < self.opening_open:
                        self.sess_direction = -1
                    else:
                        self.sess_direction = 0

                    hist_count = len(self.opening_vol_history)
                    hist_sum = sum(self.opening_vol_history) if hist_count > 0 else None
                    hist_ready = hist_count == LOOKBACK and not _na(hist_sum) and hist_sum > 0
                    self.sess_opening_rvol = (
                        self.opening_volume / (hist_sum / LOOKBACK)
                        if self.sess_has_opening and hist_ready else None
                    )

                    pass_price = self.sess_has_opening and self.opening_open > MIN_OPEN_PRICE
                    pass_liq = (not _na(bar.prev_daily_vol_sum)
                                and bar.prev_daily_vol_sum >= MIN_AVG_DAILY_VOL * LOOKBACK)
                    pass_atr = not _na(bar.prev_daily_atr) and bar.prev_daily_atr > MIN_DAILY_ATR
                    pass_rvol = (self.sess_has_opening and hist_ready
                                 and self.opening_volume * LOOKBACK >= MIN_OPEN_RVOL * hist_sum)

                    self.sess_prev_atr = bar.prev_daily_atr
                    self.sess_prev_avg_vol = (None if _na(bar.prev_daily_vol_sum)
                                              else bar.prev_daily_vol_sum / LOOKBACK)
                    self.sess_eligible = (self.setup_is_valid and self.sess_has_opening
                                          and self.sess_direction != 0 and pass_price
                                          and pass_liq and pass_atr and pass_rvol)

                    if volume_valid:
                        self.opening_vol_history.append(self.opening_volume)
                        if len(self.opening_vol_history) > LOOKBACK:
                            self.opening_vol_history.pop(0)
            else:
                in_signal_window = WINDOW_START_MOD <= ny_mod < WINDOW_END_MOD
                if self.sess_eligible and not self.sess_signal_locked and in_signal_window:
                    if self.sess_direction == 1 and bar.close > self.opening_high:
                        buy_signal = True
                        self.sess_signal_locked = True
                    elif self.sess_direction == -1 and bar.close < self.opening_low:
                        sell_signal = True
                        self.sess_signal_locked = True

        return buy_signal, sell_signal


def position_size(equity: float, prev_daily_atr: float, signal_close: float, mintick: float) -> int:
    """Mirror of strategy section S4: whole shares allowed by risk AND notional cap."""
    stop_distance = prev_daily_atr * STOP_ATR_FRACTION
    risk_budget = equity * RISK_FRACTION
    reference_px = signal_close + SLIPPAGE_TICKS * mintick
    shares_by_risk = math.floor(risk_budget / stop_distance + QTY_EPSILON) if stop_distance > 0 else 0
    shares_by_cap = (math.floor(equity * MAX_NOTIONAL_FRACTION / reference_px + QTY_EPSILON)
                     if reference_px > 0 else 0)
    return min(shares_by_risk, shares_by_cap)
