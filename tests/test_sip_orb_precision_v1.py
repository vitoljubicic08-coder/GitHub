"""Validation tests for SIP-ORB Precision V1.

Two groups:
  1. Behavioural tests A-I (plus boundaries) run against the offline reference
     model in sip_orb_reference_engine.py, which mirrors the Pine engine.
  2. Static checks on the two .pine files: identical signal engine, no
     forbidden visual elements, non-repainting request pattern, fixed
     strategy properties.

Run:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import re
import sys
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sip_orb_reference_engine import TZ, Bar, SipOrbEngine, position_size  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
INDICATOR = REPO / "sip_orb_precision_v1_indicator.pine"
STRATEGY = REPO / "sip_orb_precision_v1_strategy.pine"

DEFAULT_ATR = 1.00                     # previous daily ATR(14) > 0.50
DEFAULT_VOL_SUM = 14 * 2_000_000.0     # previous 14-day mean volume = 2,000,000
TEST_DAY = date(2026, 6, 17)           # a Wednesday (EDT)


# ----------------------------------------------------------------------------
# Scenario helpers
# ----------------------------------------------------------------------------
def ny_utc(d: date, hh: int, mm: int) -> datetime:
    """Bar open time given in New York local time, returned in UTC."""
    return datetime.combine(d, time(hh, mm), tzinfo=TZ).astimezone(timezone.utc)


def bar(d: date, hh: int, mm: int, o, h, l, c, v, **kw) -> Bar:
    kw.setdefault("prev_daily_atr", DEFAULT_ATR)
    kw.setdefault("prev_daily_vol_sum", DEFAULT_VOL_SUM)
    return Bar(ny_utc(d, hh, mm), o, h, l, c, v, **kw)


def weekdays_before(d: date, n: int) -> list[date]:
    days, cur = [], d
    while len(days) < n:
        cur -= timedelta(days=1)
        if cur.weekday() <= 4:
            days.append(cur)
    return sorted(days)


def history(test_day: date, n: int = 14, opening_volume: float = 100_000) -> list[Bar]:
    """n prior sessions with doji openings (so they never signal themselves)."""
    bars: list[Bar] = []
    for d in weekdays_before(test_day, n):
        bars.append(bar(d, 9, 30, 50.0, 50.5, 49.5, 50.0, opening_volume))
        bars.append(bar(d, 9, 35, 50.0, 50.2, 49.8, 50.1, 60_000))
    return bars


def bullish_open(d: date, volume: float = 250_000, **kw) -> Bar:
    """Test A opening candle: O 100.00 H 100.50 L 99.80 C 100.30."""
    return bar(d, 9, 30, 100.00, 100.50, 99.80, 100.30, volume, **kw)


def bearish_open(d: date, volume: float = 250_000, **kw) -> Bar:
    return bar(d, 9, 30, 100.00, 100.10, 99.50, 99.70, volume, **kw)


def run(bars: list[Bar], engine: SipOrbEngine | None = None):
    """Feed bars in order; return (engine, [(kind, utc_time, close), ...])."""
    engine = engine or SipOrbEngine()
    signals = []
    for b in bars:
        buy, sell = engine.update(b)
        assert not (buy and sell), "BUY and SELL on the same bar"
        if buy:
            signals.append(("BUY", b.time, b.close))
        if sell:
            signals.append(("SELL", b.time, b.close))
    return engine, signals


def on_day(signals, d: date):
    return [s for s in signals if s[1].astimezone(TZ).date() == d]


# ----------------------------------------------------------------------------
# 1. Behavioural tests (specification section 13)
# ----------------------------------------------------------------------------
class SpecificationTests(unittest.TestCase):

    def test_A_valid_buy(self):
        bars = history(TEST_DAY) + [
            bullish_open(TEST_DAY),
            bar(TEST_DAY, 9, 35, 100.30, 100.65, 100.25, 100.60, 120_000),
        ]
        engine, signals = run(bars)
        self.assertAlmostEqual(engine.sess_opening_rvol, 2.5)
        self.assertEqual(engine.sess_direction, 1)
        self.assertTrue(engine.sess_eligible)
        self.assertEqual(on_day(signals, TEST_DAY),
                         [("BUY", ny_utc(TEST_DAY, 9, 35), 100.60)])

    def test_B_wick_without_close_is_rejected(self):
        bars = history(TEST_DAY) + [
            bullish_open(TEST_DAY),
            bar(TEST_DAY, 9, 35, 100.30, 100.70, 100.20, 100.45, 120_000),
            bar(TEST_DAY, 9, 40, 100.45, 100.80, 100.30, 100.50, 90_000),  # close == high: not strictly above
        ]
        _, signals = run(bars)
        self.assertEqual(on_day(signals, TEST_DAY), [])

    def test_C_valid_sell(self):
        bars = history(TEST_DAY) + [
            bearish_open(TEST_DAY),
            bar(TEST_DAY, 9, 35, 99.70, 99.80, 99.45, 99.60, 100_000),  # wick below 99.50 only
            bar(TEST_DAY, 9, 40, 99.60, 99.65, 99.30, 99.40, 100_000),  # confirmed close below
        ]
        engine, signals = run(bars)
        self.assertEqual(engine.sess_direction, -1)
        self.assertEqual(on_day(signals, TEST_DAY),
                         [("SELL", ny_utc(TEST_DAY, 9, 40), 99.40)])

    def test_D_rvol_below_threshold_is_rejected(self):
        bars = history(TEST_DAY) + [
            bullish_open(TEST_DAY, volume=199_000),                         # RVOL 1.99
            bar(TEST_DAY, 9, 35, 100.30, 101.50, 100.30, 101.40, 300_000),  # big breakout
        ]
        engine, signals = run(bars)
        self.assertAlmostEqual(engine.sess_opening_rvol, 1.99)
        self.assertFalse(engine.sess_eligible)
        self.assertEqual(on_day(signals, TEST_DAY), [])

    def test_D_rvol_exactly_two_is_accepted(self):
        bars = history(TEST_DAY) + [
            bullish_open(TEST_DAY, volume=200_000),
            bar(TEST_DAY, 9, 35, 100.30, 100.65, 100.25, 100.60, 120_000),
        ]
        _, signals = run(bars)
        self.assertEqual(len(on_day(signals, TEST_DAY)), 1)

    def test_E_opening_doji_blocks_the_day(self):
        bars = history(TEST_DAY) + [
            bar(TEST_DAY, 9, 30, 100.00, 100.50, 99.50, 100.00, 250_000),
            bar(TEST_DAY, 9, 35, 100.00, 100.90, 99.90, 100.80, 150_000),  # above high
            bar(TEST_DAY, 9, 40, 100.80, 100.80, 99.00, 99.20, 150_000),   # below low
        ]
        engine, signals = run(bars)
        self.assertEqual(engine.sess_direction, 0)
        self.assertEqual(on_day(signals, TEST_DAY), [])

    def test_F_one_signal_per_session_then_reset(self):
        next_day = TEST_DAY + timedelta(days=1)
        bars = history(TEST_DAY) + [
            bullish_open(TEST_DAY),
            bar(TEST_DAY, 9, 35, 100.30, 100.65, 100.25, 100.60, 120_000),  # BUY
            bar(TEST_DAY, 9, 40, 100.60, 100.60, 100.00, 100.10, 120_000),
            bar(TEST_DAY, 9, 45, 100.10, 101.00, 100.10, 100.95, 120_000),  # 2nd breakout: ignored
            bar(TEST_DAY, 9, 50, 100.95, 101.50, 100.90, 101.40, 120_000),  # ignored
            bullish_open(next_day),
            bar(next_day, 9, 35, 100.30, 100.40, 100.20, 100.35, 100_000),
            bar(next_day, 10, 15, 100.35, 100.80, 100.30, 100.70, 100_000),  # new session's BUY
        ]
        _, signals = run(bars)
        self.assertEqual(on_day(signals, TEST_DAY), [("BUY", ny_utc(TEST_DAY, 9, 35), 100.60)])
        self.assertEqual(on_day(signals, next_day), [("BUY", ny_utc(next_day, 10, 15), 100.70)])

    def test_G_realtime_replay_matches_history(self):
        """Signals from tick-by-tick real-time processing equal the reloaded history."""
        confirmed = history(TEST_DAY) + [
            bullish_open(TEST_DAY),
            bar(TEST_DAY, 9, 35, 100.30, 100.75, 100.20, 100.40, 120_000),  # crosses intrabar, closes below
            bar(TEST_DAY, 9, 40, 100.40, 100.70, 100.35, 100.62, 120_000),  # confirmed BUY
            bar(TEST_DAY, 9, 45, 100.62, 101.00, 100.50, 100.90, 120_000),
        ]
        _, historical = run(confirmed)

        # Real time: each test-day bar is preceded by unconfirmed tick snapshots,
        # including ones where the developing close is above the opening high.
        engine = SipOrbEngine()
        realtime = []
        for b in confirmed:
            if b.time.astimezone(TZ).date() == TEST_DAY:
                for tick_close in (b.open, b.high, (b.high + b.low) / 2):
                    tick = Bar(b.time, b.open, b.high, b.low, tick_close, b.volume / 2,
                               b.prev_daily_atr, b.prev_daily_vol_sum, confirmed=False)
                    self.assertEqual(engine.update(tick), (False, False),
                                     "signal emitted on an unconfirmed bar")
            buy, sell = engine.update(b)
            if buy:
                realtime.append(("BUY", b.time, b.close))
            if sell:
                realtime.append(("SELL", b.time, b.close))

        self.assertEqual(realtime, historical)
        self.assertEqual(on_day(historical, TEST_DAY), [("BUY", ny_utc(TEST_DAY, 9, 40), 100.62)])

    def test_H_window_tracks_new_york_time_across_dst(self):
        for d, utc_hour_at_0935 in ((date(2026, 1, 14), 14),    # EST, UTC-5
                                    (date(2026, 7, 15), 13),    # EDT, UTC-4
                                    (date(2026, 3, 9), 13),     # first session after DST starts
                                    (date(2026, 11, 2), 14)):   # first session after DST ends
            with self.subTest(day=d):
                bars = history(d) + [
                    bullish_open(d),
                    bar(d, 9, 35, 100.30, 100.65, 100.25, 100.60, 120_000),
                ]
                _, signals = run(bars)
                got = on_day(signals, d)
                self.assertEqual(len(got), 1)
                self.assertEqual(got[0][1].hour, utc_hour_at_0935)
                self.assertEqual(got[0][1].astimezone(TZ).strftime("%H:%M"), "09:35")

    def test_H_window_end_is_exclusive_at_11_00_local(self):
        for d in (date(2026, 1, 14), date(2026, 7, 15)):
            with self.subTest(day=d, case="10:55 bar signals"):
                bars = history(d) + [bullish_open(d),
                                     bar(d, 10, 55, 100.30, 100.70, 100.20, 100.60, 90_000)]
                self.assertEqual(len(on_day(run(bars)[1], d)), 1)
            with self.subTest(day=d, case="11:00 bar does not"):
                bars = history(d) + [bullish_open(d),
                                     bar(d, 11, 0, 100.30, 100.70, 100.20, 100.60, 90_000)]
                self.assertEqual(on_day(run(bars)[1], d), [])

    def test_I_insufficient_opening_volume_history(self):
        def scenario(n_history):
            return history(TEST_DAY, n=n_history) + [
                bullish_open(TEST_DAY),
                bar(TEST_DAY, 9, 35, 100.30, 100.65, 100.25, 100.60, 120_000),
            ]
        self.assertEqual(on_day(run(scenario(13))[1], TEST_DAY), [])
        self.assertEqual(len(on_day(run(scenario(14))[1], TEST_DAY)), 1)

    def test_I_invalid_history_observation_is_not_counted(self):
        bars = history(TEST_DAY)
        idx = next(i for i, b in enumerate(bars) if b.time.astimezone(TZ).minute == 30)
        b0 = bars[idx]
        bars[idx] = Bar(b0.time, b0.open, b0.high, b0.low, b0.close, 0.0,
                        b0.prev_daily_atr, b0.prev_daily_vol_sum)   # zero-volume opening
        bars += [bullish_open(TEST_DAY),
                 bar(TEST_DAY, 9, 35, 100.30, 100.65, 100.25, 100.60, 120_000)]
        engine, signals = run(bars)
        self.assertEqual(on_day(signals, TEST_DAY), [])
        self.assertEqual(len(engine.opening_vol_history), 14)  # today's volume now included


# ----------------------------------------------------------------------------
# 1b. Filter boundaries, missing data and session handling
# ----------------------------------------------------------------------------
class FilterAndSessionTests(unittest.TestCase):

    def _buy_count(self, opening: Bar, **breakout_kw) -> int:
        breakout = bar(TEST_DAY, 9, 35, 100.30, 100.65, 100.25, 100.60, 120_000, **breakout_kw)
        return len(on_day(run(history(TEST_DAY) + [opening, breakout])[1], TEST_DAY))

    def test_filter_A_price_strictly_above_5(self):
        def opening(o):
            return bar(TEST_DAY, 9, 30, o, o + 0.50, o - 0.20, o + 0.30, 250_000)
        def count(o):
            breakout = bar(TEST_DAY, 9, 35, o + 0.3, o + 0.7, o + 0.2, o + 0.60, 120_000)
            return len(on_day(run(history(TEST_DAY) + [opening(o), breakout])[1], TEST_DAY))
        self.assertEqual(count(5.00), 0)
        self.assertEqual(count(5.01), 1)

    def test_filter_B_daily_liquidity(self):
        self.assertEqual(self._buy_count(bullish_open(TEST_DAY, prev_daily_vol_sum=14 * 999_999.0)), 0)
        self.assertEqual(self._buy_count(bullish_open(TEST_DAY, prev_daily_vol_sum=14 * 1_000_000.0)), 1)

    def test_filter_C_daily_atr_strictly_above_050(self):
        self.assertEqual(self._buy_count(bullish_open(TEST_DAY, prev_daily_atr=0.50)), 0)
        self.assertEqual(self._buy_count(bullish_open(TEST_DAY, prev_daily_atr=0.51)), 1)

    def test_missing_daily_data_blocks_signals(self):
        self.assertEqual(self._buy_count(bullish_open(TEST_DAY, prev_daily_atr=None)), 0)
        self.assertEqual(self._buy_count(bullish_open(TEST_DAY, prev_daily_vol_sum=None)), 0)

    def test_daily_values_are_frozen_at_the_opening_bar(self):
        # Later bars report different daily values; the session must ignore them.
        self.assertEqual(self._buy_count(bullish_open(TEST_DAY), prev_daily_atr=0.10,
                                         prev_daily_vol_sum=0.0), 1)

    def test_missing_0930_candle_blocks_the_session(self):
        bars = history(TEST_DAY) + [
            bar(TEST_DAY, 9, 35, 100.00, 100.50, 99.80, 100.30, 250_000),
            bar(TEST_DAY, 9, 40, 100.30, 100.90, 100.25, 100.80, 120_000),
        ]
        self.assertEqual(on_day(run(bars)[1], TEST_DAY), [])

    def test_opening_bar_itself_never_signals(self):
        bars = history(TEST_DAY) + [bullish_open(TEST_DAY)]
        self.assertEqual(on_day(run(bars)[1], TEST_DAY), [])

    def test_extended_hours_bars_are_ignored(self):
        pre = [bar(TEST_DAY, 8, m, 100.0, 105.0, 99.0, 104.0, 5_000_000, is_market=False)
               for m in (0, 30, 55)]
        post = [bar(TEST_DAY, 16, 0, 100.0, 105.0, 99.0, 104.0, 5_000_000, is_market=False)]
        bars = history(TEST_DAY) + pre + [
            bullish_open(TEST_DAY),
            bar(TEST_DAY, 9, 35, 100.30, 100.40, 100.20, 100.35, 100_000),
            bar(TEST_DAY, 9, 40, 100.35, 100.70, 100.30, 100.60, 100_000),
        ] + post
        engine, signals = run(bars)
        self.assertAlmostEqual(engine.sess_opening_rvol, 2.5)
        self.assertEqual(on_day(signals, TEST_DAY), [("BUY", ny_utc(TEST_DAY, 9, 40), 100.60)])

    def test_invalid_setup_blocks_everything(self):
        bars = history(TEST_DAY) + [bullish_open(TEST_DAY),
                                    bar(TEST_DAY, 9, 35, 100.30, 100.65, 100.25, 100.60, 120_000)]
        self.assertEqual(run(bars, SipOrbEngine(setup_is_valid=False))[1], [])

    def test_rolling_history_keeps_last_14_in_order(self):
        bars = []
        days = weekdays_before(TEST_DAY, 20)
        for i, d in enumerate(days):
            bars.append(bar(d, 9, 30, 50.0, 50.5, 49.5, 50.0, 1_000 + i))
        engine, _ = run(bars)
        self.assertEqual(engine.opening_vol_history, [1_000.0 + i for i in range(6, 20)])


class PositionSizingTests(unittest.TestCase):

    def test_notional_cap_binds(self):
        # risk: 25 / 0.20 = 125 shares; cap: floor(10000 / 100.02) = 99 shares
        self.assertEqual(position_size(10_000, 2.00, 100.00, 0.01), 99)

    def test_risk_budget_binds(self):
        # risk: 25 / 0.10 = 250 shares; cap: floor(10000 / 20.02) = 499 shares
        self.assertEqual(position_size(10_000, 1.00, 20.00, 0.01), 250)

    def test_floor_is_protected_against_binary_rounding(self):
        # 10200 * 0.0025 / (1.02 * 0.10) evaluates to 249.99999999999997 in IEEE-754.
        self.assertLess(10_200 * 0.0025 / (1.02 * 0.10), 250)
        self.assertEqual(position_size(10_200, 1.02, 20.00, 0.01), 250)

    def test_less_than_one_share_means_no_trade(self):
        self.assertEqual(position_size(50, 10.00, 400.00, 0.01), 0)


# ----------------------------------------------------------------------------
# 2. Static checks on the Pine sources
# ----------------------------------------------------------------------------
ENGINE_RE = re.compile(r"// ==== BEGIN SIP-ORB SIGNAL ENGINE.*?// ==== END SIP-ORB SIGNAL ENGINE ====", re.S)


def strip_comments(src: str) -> str:
    """Remove // comments that are not inside string literals."""
    out = []
    for line in src.splitlines():
        in_str, quote, cut = False, "", len(line)
        i = 0
        while i < len(line):
            ch = line[i]
            if in_str:
                if ch == "\\":
                    i += 1
                elif ch == quote:
                    in_str = False
            elif ch in "\"'":
                in_str, quote = True, ch
            elif line.startswith("//", i):
                cut = i
                break
            i += 1
        out.append(line[:cut])
    return "\n".join(out)


class PineSourceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ind_src = INDICATOR.read_text(encoding="utf-8")
        cls.str_src = STRATEGY.read_text(encoding="utf-8")
        cls.ind = strip_comments(cls.ind_src)
        cls.strat = strip_comments(cls.str_src)

    def test_version_6(self):
        for src in (self.ind_src, self.str_src):
            self.assertTrue(src.startswith("//@version=6\n"))

    def test_signal_engine_is_byte_identical(self):
        a, b = ENGINE_RE.findall(self.ind_src), ENGINE_RE.findall(self.str_src)
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)
        self.assertEqual(a[0], b[0])

    def test_engine_gates_on_confirmed_bars(self):
        engine = strip_comments(ENGINE_RE.search(self.ind_src).group(0))
        self.assertIn("if barstate.isconfirmed and inRegular", engine)

    def test_no_inputs_anywhere(self):
        for code in (self.ind, self.strat):
            self.assertNotRegex(code, r"\binput\s*[.(]")

    def test_indicator_draws_only_two_arrows(self):
        forbidden = [r"\bbgcolor\s*\(", r"\bbarcolor\s*\(", r"\bfill\s*\(", r"\bhline\s*\(",
                     r"\bline\.new\b", r"\blabel\.new\b", r"\bbox\.new\b", r"\btable\.new\b",
                     r"\bpolyline\.new\b", r"\blinefill\.new\b", r"\bplotchar\s*\(",
                     r"\bplotarrow\s*\(", r"\bplotcandle\s*\(", r"\bplotbar\s*\("]
        for pattern in forbidden:
            self.assertNotRegex(self.ind, pattern)
        self.assertEqual(len(re.findall(r"\bplotshape\s*\(", self.ind)), 2)
        plots = re.findall(r"^\s*plot\s*\(.*$", self.ind, re.M)
        self.assertTrue(plots)
        for p in plots:
            self.assertIn("display = display.data_window", p)

    def test_arrow_specification(self):
        buy = re.search(r"plotshape\(buySignal.*\)", self.ind).group(0)
        sell = re.search(r"plotshape\(sellSignal.*\)", self.ind).group(0)
        for token in ("shape.arrowup", "location.belowbar", "color.rgb(0, 200, 0)", "size.small"):
            self.assertIn(token, buy)
        for token in ("shape.arrowdown", "location.abovebar", "color.rgb(220, 0, 0)", "size.small"):
            self.assertIn(token, sell)

    def test_no_offsets_or_lookahead_leaks(self):
        for code in (self.ind, self.strat):
            self.assertNotRegex(code, r"\boffset\s*=")
            calls = re.findall(r"request\.security\(.*\)", code)
            self.assertEqual(len(calls), 1)
            self.assertIn("lookahead = barmerge.lookahead_on", calls[0])
            self.assertIn("ta.atr(LOOKBACK)[1]", calls[0])
            self.assertIn("math.sum(volume, LOOKBACK)[1]", calls[0])
            self.assertNotRegex(code, r"request\.security_lower_tf|ta\.pivot|zigzag")

    def test_alert_conditions(self):
        alerts = re.findall(r"alertcondition\((\w+), title = \"([^\"]+)\", message = \"([^\"]+)\"\)", self.ind)
        self.assertEqual([(a[0], a[1]) for a in alerts],
                         [("buySignal", "SIP-ORB BUY"), ("sellSignal", "SIP-ORB SELL")])
        for _, title, message in alerts:
            for token in ("{{ticker}}", "{{interval}}", "{{close}}", title):
                self.assertIn(token, message)

    def test_strategy_properties(self):
        header = re.search(r"strategy\((.*?)\)\n", self.strat, re.S).group(1)
        for token in ("overlay = true", "initial_capital = 10000", "pyramiding = 1",
                      "commission_type = strategy.commission.cash_per_contract",
                      "commission_value = 0.005", "slippage = 2", "margin_long = 100",
                      "margin_short = 100", "process_orders_on_close = false",
                      "calc_on_every_tick = false", "use_bar_magnifier = true"):
            self.assertIn(token, header)
        self.assertIn("SLIPPAGE_TICKS        = 2", self.strat)
        self.assertIn("RISK_FRACTION         = 0.0025", self.strat)
        self.assertIn("STOP_ATR_FRACTION     = 0.10", self.strat)
        self.assertIn("EOD_SUBMIT_MOD        = 950", self.strat)

    def test_strategy_has_no_target_or_trailing_stop(self):
        exits = re.findall(r"strategy\.exit\(.*\)", self.strat)
        self.assertEqual(len(exits), 2)
        for e in exits:
            self.assertIn("loss = stopTicks", e)
            self.assertNotRegex(e, r"\b(profit|limit|trail_points|trail_price|trail_offset|stop)\s*=")

    def test_block_indentation_and_brackets(self):
        """Cheap syntax sanity: 4-space blocks, no tabs, balanced brackets per statement."""
        for name, code in (("indicator", self.ind), ("strategy", self.strat)):
            depth = 0
            for n, line in enumerate(code.splitlines(), 1):
                self.assertNotIn("\t", line, f"{name}:{n} tab")
                if not line.strip():
                    continue
                indent = len(line) - len(line.lstrip(" "))
                if depth == 0:
                    self.assertEqual(indent % 4, 0, f"{name}:{n} block indent {indent}")
                else:
                    self.assertNotEqual(indent % 4, 0, f"{name}:{n} continuation indent {indent}")
                no_str = re.sub(r"\"[^\"]*\"", "\"\"", line)
                depth += no_str.count("(") + no_str.count("[") - no_str.count(")") - no_str.count("]")
                self.assertGreaterEqual(depth, 0, f"{name}:{n} unbalanced")
            self.assertEqual(depth, 0, f"{name}: unbalanced at EOF")


if __name__ == "__main__":
    unittest.main()
