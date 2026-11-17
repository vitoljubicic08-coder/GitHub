"""The bot runtime: data -> NB3 V2 engine -> risk guard -> execution, once per loop.

Timeline of a trading day (New York time):
  09:25      session prepared: engine state saved, feeds opened, contract resolved
  09:30-16:00 each finished minute is fetched (after a short grace period) and checked;
             each 5-minute bar is completed only when all five minutes are in (or, after the
             maximum delay, marked INCOMPLETE - a signal on an incomplete bar is never traded)
  signal     risk guard (every check logged) -> bracket entry -> fill -> stop/target verified
  15:55      open position flattened, leftover orders cancelled
  16:03      the whole session is re-downloaded and the engine state for tomorrow is rebuilt from
             final data (so history matches the backtest's definition), account end-of-day update
Every loop also: kill-switch check, reconciliation with the broker (every 15 s), status for the dashboard.
"""
from __future__ import annotations

import math
import threading
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from nb3bot.broker.base import Broker, BrokerError, ContractInfo, UncertainOrderState
from nb3bot.broker.paper import PaperBroker
from nb3bot.contracts import front_contract, projectx_contract_id
from nb3bot.data.base import SessionFeed, check_feed, check_ratio, expected_last_minute
from nb3bot.execution.manager import TradeManager
from nb3bot.risk.account import AccountTracker, rules_from_config
from nb3bot.risk.guard import TradeContext, edge_status, evaluate
from nb3bot.risk.payout import PAYOUT_PRESETS, advice as payout_advice
from nb3bot.risk.sizing import convert_stop, size_trade
from nb3bot.safety import KillSwitch, authorization_status
from nb3bot.strategy.nb3v2 import NB3V2Engine, NB3V2Params
from nb3bot.timeutil import NY, ZAGREB, TradingCalendar, fmt_dual, minute_start, session_key

PREP_TIME = time(9, 25)


@dataclass
class Day:
    key: int
    sig: SessionFeed
    exe: SessionFeed
    start_snapshot: dict
    contract: ContractInfo | None
    contract_ok: bool
    contract_detail: str
    early_close: bool
    next_fetch: datetime
    incomplete_bars: set = field(default_factory=set)
    signal: dict | None = None                 # the day's first signal (live vs final-data agreement)
    signals: list = field(default_factory=list)
    trade_keys: list = field(default_factory=list)
    awaiting: dict | None = None               # last signal waiting for its trade to close (2-trade profile)
    locked: str = ""                           # daily loss / profit lockout reason
    decision: dict | None = None
    eod_done: bool = False
    data_errors: list = field(default_factory=list)


class Bot:
    def __init__(self, cfg, *, mode: str, clock, broker: Broker, sig_source, exec_source, store, audit, alerter,
                 parity_report: str, contract: ContractInfo | None = None):
        self.cfg, self.mode, self.clock = cfg, mode, clock
        self.broker, self.sig_src, self.exe_src = broker, sig_source, exec_source
        self.store, self.audit, self.alert = store, audit, alerter
        self.parity_report = parity_report
        self.fixed_contract = contract
        self.contract_resolver = None          # optional: contract search without a trading broker (paper mode)
        self.cal = TradingCalendar()
        self.kill = KillSwitch(cfg.bot.state_dir)
        snap = store.get("account")
        self.account = AccountTracker.restore(snap) if snap else AccountTracker(rules_from_config(cfg.account))
        self.mgr = TradeManager(broker, store, audit, alerter, self.account, cfg, clock)
        self.params = NB3V2Params(reward_risk=cfg.strategy.reward_risk,
                                  max_trades_per_day=cfg.strategy.max_trades_per_day)
        self.engine: NB3V2Engine | None = None
        self.day: Day | None = None
        self.last_reconcile = datetime.min.replace(tzinfo=NY)
        self.status: dict = {}
        self.status_lock = threading.Lock()
        self.authorized, self.auth_detail = authorization_status(cfg, mode, parity_report)
        self.armed = bool(store.get("armed", mode in ("replay", "paper")))
        self.kill_handled = False
        self._last_status = -1e9

    # ------------------------------------------------------------------ start-up
    def startup(self, warmup_sessions: list | None = None) -> None:
        if self.mode in ("practice", "live") and not self.authorized:
            raise PermissionError(f"refusing to start in {self.mode} mode: {self.auth_detail}")
        self.broker.connect()
        snap = self.store.get("engine_snapshot")
        if snap:
            self.engine = NB3V2Engine.restore(snap["engine"])
            self.engine.p = self.params            # trade settings follow the configuration
            self.audit.log("engine_restored", last_session=snap["last_session"], warm=self.engine.warm())
        if warmup_sessions is not None:
            self.engine = NB3V2Engine(self.params)
            for s in warmup_sessions:
                self._feed_whole_session(self.engine, s.key, s)
            last = warmup_sessions[-1].key if warmup_sessions else None
            self.store.put("engine_snapshot", {"engine": self.engine.snapshot(), "last_session": last})
            self.audit.log("engine_warmed", sessions=len(warmup_sessions), last_session=last, warm=self.engine.warm())
        if self.engine is None:
            raise RuntimeError("no engine state: run a warm-up (see the operating manual)")
        if self.mgr.active is not None:
            self.audit.log("recovering_trade", "WARN", tag=self.mgr.active.tag, state=self.mgr.active.state)
            if self.mgr.active.state == "OPEN":
                self.mgr.active.state = "PROTECTING"
                self.mgr.active.protect_since = (self.clock.now() - timedelta(seconds=60)).isoformat()
        self.mgr.reconcile(self._contract_ids())
        self.audit.log("startup", mode=self.mode, authorized=self.authorized, detail=self.auth_detail, armed=self.armed,
                       broker=self.broker.name, time=fmt_dual(self.clock.now()))

    def _feed_whole_session(self, eng: NB3V2Engine, key: int, s) -> list:
        """Feed a complete historical session (Session or SessionFeed) to an engine; returns its signals."""
        eng.begin_session(key)
        if isinstance(s, SessionFeed):
            mins = [(m, b.o, b.h, b.l, b.c) for m, b in sorted(s.bars.items())]
        else:
            mins = [(m, o, h, l, c) for m, o, h, l, c, _ in s.minutes()]
        i, sigs = 0, []
        for b in range(78):
            while i < len(mins) and mins[i][0] < 5 * b + 5:
                eng.on_minute(*mins[i])
                i += 1
            x = eng.complete_bar(b)
            if x is not None:
                sigs.append(x)
        eng.end_session()
        return sigs

    def _contract_ids(self) -> list[str]:
        return [self.day.contract.id] if self.day and self.day.contract else []

    # ------------------------------------------------------------------ control
    def set_armed(self, on: bool, why: str) -> None:
        self.armed = on
        self.store.put("armed", on)
        self.audit.log("armed" if on else "disarmed", reason=why)

    def _resolve_contract(self, d: date) -> tuple[ContractInfo | None, bool, str]:
        if self.fixed_contract is not None:
            return self.fixed_contract, True, f"{self.fixed_contract.id} (fixed)"
        y, m, exp = front_contract(d, self.cfg.instrument.roll_days_before_expiry)
        want = projectx_contract_id(self.cfg.instrument.symbol, y, m)
        try:
            cs = (self.contract_resolver or self.broker.contracts)(self.cfg.instrument.symbol)
        except BrokerError as e:
            return None, False, f"contract lookup failed: {e}"
        match = [c for c in cs if c.id == want]
        active = [c for c in cs if c.active and f".{self.cfg.instrument.symbol}." in c.id]
        if match and match[0].active:
            c = match[0]
            if abs(c.tick_size - self.cfg.instrument.tick_size) > 1e-12 or abs(c.tick_value - self.cfg.instrument.tick_value) > 1e-9:
                return c, False, f"{c.id} tick {c.tick_size}/{c.tick_value} differs from config"
            return c, True, f"{c.id} (expires {exp})"
        return (match[0] if match else (active[0] if active else None)), False, \
            f"calendar says {want}, broker active: {[c.id for c in active]} - entries paused until they agree"

    # ------------------------------------------------------------------ the loop
    def step(self) -> None:
        now = self.clock.now()
        ny = now.astimezone(NY)
        d = ny.date()
        if self.kill.active() and not self.kill_handled:
            self._on_kill(self.kill.reason())
        if self.cal.is_trading_day(d) and ny.time() >= PREP_TIME and (self.day is None or self.day.key < session_key(d)):
            if self.day is not None and not self.day.eod_done:
                self._end_day(now)
            self._begin_day(d, now)
        if self.day is not None and not self.day.eod_done:
            self._poll(now)
            self._complete_bars(now)
            self._mark(now)
            self._daily_limits()
        self.mgr.tick()
        if (now - self.last_reconcile).total_seconds() >= 15:
            self.last_reconcile = now
            self.mgr.reconcile(self._contract_ids())
        if self.day is not None and not self.day.eod_done:
            close = datetime.combine(key_date(self.day.key), self.cal.close_time(key_date(self.day.key)), NY)
            if now >= close + timedelta(minutes=self.cfg.data.eod_rebuild_delay_minutes) and self.mgr.active is None:
                self._end_day(now)
        self._publish_status(now)

    def _begin_day(self, d: date, now: datetime) -> None:
        key = session_key(d)
        self._catch_up(key)
        c, ok, detail = self._resolve_contract(d)
        if c is not None:
            for src in (self.exe_src, self.sig_src):
                if hasattr(src, "contract_id") and self.fixed_contract is None:
                    src.contract_id = c.id          # follow the quarterly roll
            if isinstance(self.broker, PaperBroker) and self.broker.pos.size == 0 and self.fixed_contract is None:
                self.broker.c = c
        start = self.engine.snapshot()
        self.engine.begin_session(key)
        sym = self.cfg.strategy.signal_source
        self.day = Day(key, SessionFeed(sym, key), SessionFeed(self.cfg.instrument.symbol, key), start, c, ok, detail,
                       self.cal.is_early_close(d), now)
        if self.account.s.day_start_balance != self.account.s.balance:
            self.account.s.day_start_balance = self.account.s.balance
        self.audit.log("session_start", session=key, contract=detail, early_close=self.day.early_close,
                       engine_warm=self.engine.warm(), time=fmt_dual(now))
        if not ok:
            self.alert.send(f"Contract check failed for {key}: {detail}", "WARN")

    def _catch_up(self, key: int) -> None:
        """If sessions were missed (bot off), rebuild the engine history from final data first."""
        snap = self.store.get("engine_snapshot") or {}
        last = snap.get("last_session")
        if last is None:
            return
        d = key_date(last)
        missing = []
        while True:
            d = self.cal.next_trading_day(d)
            if session_key(d) >= key:
                break
            missing.append(session_key(d))
        for k in missing:
            feed = self._download_session(self.sig_src, self.cfg.strategy.signal_source, k)
            self._feed_whole_session(self.engine, k, feed)
            self.audit.log("engine_catch_up", session=k, bars=len(feed.bars))
        if missing:
            self.store.put("engine_snapshot", {"engine": self.engine.snapshot(), "last_session": missing[-1]})

    def _download_session(self, src, symbol: str, key: int) -> SessionFeed:
        f = SessionFeed(symbol, key)
        for b in src.fetch(minute_start(key, 0), minute_start(key, 390)):
            f.add(b)
        return f

    def _poll(self, now: datetime) -> None:
        day = self.day
        if now < day.next_fetch:
            return
        due = expected_last_minute(now, day.key, self.cfg.data.bar_grace_seconds)
        if due < 0:
            day.next_fetch = minute_start(day.key, 0) + timedelta(seconds=60 + self.cfg.data.bar_grace_seconds)
            return
        missing_any = False
        settled = expected_last_minute(now, day.key, self.cfg.data.max_bar_delay_seconds)
        for feed, src, is_sig in ((day.sig, self.sig_src, True), (day.exe, self.exe_src, False)):
            want = [m for m in range(max(settled + 1, 0), due + 1) if m not in feed.bars]
            if not want:
                continue
            start = minute_start(day.key, want[0])
            try:
                bars = src.fetch(start, minute_start(day.key, due + 1))
            except Exception as e:  # noqa: BLE001 - provider errors are data problems, never crashes
                day.data_errors.append(f"{now.astimezone(NY):%H:%M:%S} {src.name}: {e}")
                day.data_errors = day.data_errors[-20:]
                self.alert.send(f"Market data error from {src.name}: {e}", "WARN", key=f"data-{src.name}")
                missing_any = True
                continue
            for b in bars:
                m = feed.add(b)
                if m is None:
                    continue
                if is_sig and self.engine.s is not None and m >= 5 * self.engine.s.next_bar:
                    self.engine.on_minute(m, b.o, b.h, b.l, b.c)
                if not is_sig and isinstance(self.broker, PaperBroker):
                    self.broker.on_minute(b)
            if any(m not in feed.bars for m in want):
                missing_any = True
        nxt = minute_start(day.key, due + 1) + timedelta(seconds=60 + self.cfg.data.bar_grace_seconds)
        day.next_fetch = now + timedelta(seconds=5) if missing_any else nxt

    def _complete_bars(self, now: datetime) -> None:
        day, eng = self.day, self.engine
        grace, maxd = self.cfg.data.bar_grace_seconds, self.cfg.data.max_bar_delay_seconds
        while eng.s is not None and eng.s.next_bar < 78:
            b = eng.s.next_bar
            bar_end = minute_start(day.key, 5 * b + 5)
            if now < bar_end + timedelta(seconds=grace):
                return
            missing = [m for m in range(5 * b, 5 * b + 5) if m not in day.sig.bars]
            close = datetime.combine(key_date(day.key), self.cal.close_time(key_date(day.key)), NY)
            after_close = bar_end > close
            if missing and not after_close and now < bar_end + timedelta(seconds=maxd):
                return
            if missing and not after_close:
                if not self.cfg.data.allow_empty_minutes or self._sig_stale(bar_end):
                    day.incomplete_bars.add(b)
                    self.audit.log("incomplete_bar", "WARN", bar=b, missing=len(missing))
            if eng.waiting_for_release:
                self._release_if_closed()
            sig = eng.complete_bar(b)
            if sig is not None:
                self._on_signal(sig.to_dict(), bar_end, now, incomplete=b in day.incomplete_bars)

    def _release_if_closed(self) -> None:
        """2-trade profile: once the last signal's trade is closed, let later bars signal again (from the
        minute after its exit, as in the research). A signal that was not traded releases at its entry minute."""
        day = self.day
        if day.awaiting is None:
            return
        if self.mgr.active is not None:
            self.mgr.tick()                          # pick up a fill that happened in this bar's minutes
            if self.mgr.active is not None:
                return
        lc = self.mgr.last_closed
        if day.awaiting.get("skipped"):
            m = day.awaiting["entry_minute"]
        elif lc and lc.get("trade_key") == day.awaiting["trade_key"]:
            m = lc["exit_minute"]
        else:
            return
        self.engine.release(m)
        self.audit.log("next_signal_allowed", after_minute=m, trades_today=len(day.trade_keys))
        day.awaiting = None

    def _sig_stale(self, at: datetime) -> bool:
        """Single-exchange feeds: stale if the newest signal bar is older than stale_after_seconds at `at`."""
        bars = self.day.sig.bars
        if not bars:
            return True
        newest = minute_start(self.day.key, max(bars)) + timedelta(minutes=1)
        return (at - newest).total_seconds() > self.cfg.data.stale_after_seconds

    def _mark(self, now: datetime) -> None:
        t = self.mgr.active
        if t is None or t.fill_price is None or not self.day.exe.bars:
            if t is None:
                self.account.mark(0.0)
            return
        last = self.day.exe.bars[max(self.day.exe.bars)].c
        self.account.mark(t.side * (last - t.fill_price) * (t.filled_size or t.size) * t.tick_value / t.tick_size)

    def daily_loss_limit(self) -> float:
        """The stricter of the personal daily loss limit and the firm's daily loss limit (if it has one)."""
        firm = self.account.r.daily_loss_limit
        return min(self.cfg.risk.max_daily_loss, firm) if firm else self.cfg.risk.max_daily_loss

    def consistency_cap(self) -> float | None:
        r = self.account.r
        if self.cfg.risk.phase != "evaluation" or not self.cfg.risk.consistency_day_cap or not (r.consistency and r.profit_target):
            return None
        return r.consistency * r.profit_target

    def _daily_limits(self) -> None:
        """While trading: today's P&L including the open trade against the daily loss limit and profit cap."""
        day, t, rk = self.day, self.mgr.active, self.cfg.risk
        pnl = self.account.day_pnl()
        open_trade = t is not None and t.state in ("OPEN", "PROTECTING")
        lim = self.daily_loss_limit()
        if pnl <= -lim:
            if not day.locked:
                day.locked = f"daily loss limit reached: today {pnl:+,.2f} <= -${lim:,.0f}; no more entries today"
                self.audit.log("daily_loss_lockout", "WARN", day_pnl=round(pnl, 2), limit=lim)
                self.alert.send(day.locked, "WARN", key=f"dll-{day.key}")
            if open_trade and rk.flatten_on_daily_loss:
                self.mgr.flatten(t, "DAILY_LOSS_LIMIT")
        elif rk.max_daily_profit > 0 and pnl >= rk.max_daily_profit:
            if not day.locked:
                day.locked = f"daily profit cap reached: today {pnl:+,.2f} >= ${rk.max_daily_profit:,.0f}; no more entries today"
                self.audit.log("daily_profit_lockout", day_pnl=round(pnl, 2), cap=rk.max_daily_profit)
                self.alert.send(day.locked, "INFO", key=f"dpc-{day.key}")
            if open_trade and rk.flatten_on_daily_profit:
                self.mgr.flatten(t, "DAILY_PROFIT_CAP")

    # ------------------------------------------------------------------ signals
    def _on_signal(self, sig: dict, bar_end: datetime, now: datetime, incomplete: bool) -> None:
        day = self.day
        seq = len(day.signals)
        sig["trade_key"] = day.key if seq == 0 else day.key * 10 + seq
        if seq == 0:
            day.signal = sig
        day.signals.append(sig)
        day.trade_keys.append(sig["trade_key"])
        day.awaiting = {"trade_key": sig["trade_key"], "entry_minute": sig["entry_minute"], "skipped": False}
        side = "BUY" if sig["direction"] > 0 else "SELL"
        self.store.record_signal({**sig, "session": sig["trade_key"], "day": day.key})
        self.audit.log("signal", side=side, session=sig["session"], bar=sig["bar"], close=sig["close"],
                       upper=sig["upper"], lower=sig["lower"], stop_distance=sig["stop_distance"], time=fmt_dual(bar_end))
        self.alert.send(f"NB3 V2 {side} signal on the {(bar_end - timedelta(minutes=5)).astimezone(NY):%H:%M} bar "
                        f"({fmt_dual(bar_end)})", "INFO", key=f"sig-{sig['trade_key']}")
        m_last = 5 * sig["bar"] + 4
        exec_px = day.exe.last_close(m_last)
        sig_px = sig["close"]
        method = self.cfg.instrument.stop_conversion
        stop_pts = convert_stop(sig["stop_distance"], method, sig_px, exec_px)
        tick, tv = (day.contract.tick_size, day.contract.tick_value) if day.contract else (self.cfg.instrument.tick_size, self.cfg.instrument.tick_value)
        firm_max = self.account.max_contracts_now()
        sizing = size_trade(stop_pts, self.cfg.risk_budget, tick_size=tick, tick_value=tv,
                            commission_rt=self.cfg.costs.commission_round_turn,
                            slip_ticks_per_side=self.cfg.costs.slippage_ticks_per_side,
                            extra_stop_slip_ticks=self.cfg.costs.extra_stop_slippage_ticks,
                            reward_risk=self.params.reward_risk, max_contracts=self.cfg.risk.max_contracts,
                            firm_max_contracts=firm_max)
        # market-data health for this decision
        problems = []
        if incomplete or sig["bar"] in day.incomplete_bars:
            problems.append("signal bar was incomplete (missing 1-minute data)")
        if self.cfg.data.allow_empty_minutes:
            if self._sig_stale(bar_end):
                problems.append(f"{self.sig_src.name}: no new bar for more than {self.cfg.data.stale_after_seconds:.0f}s")
        else:
            h1 = check_feed(day.sig, now, self.cfg.data.max_bar_delay_seconds + 60, range(0, m_last + 1))
            if not h1.ok:
                problems.append(h1.detail)
        if not getattr(self.sig_src, "realtime", True):
            problems.append(f"{self.sig_src.name} reports DELAYED data")
        if math.isnan(exec_px):
            problems.append(f"no {self.cfg.instrument.symbol} price at the signal")
        elif self.cfg.strategy.signal_source == "QQQ":
            hr = check_ratio(day.sig, day.exe, m_last, self.cfg.data.max_ratio_deviation)
            if not hr.ok:
                problems.append(hr.detail)
        broker_ok, broker_detail, flat = True, "connected", True
        try:
            acct = self.broker.account()
            diff = self.account.reconcile_balance(acct.balance)
            if abs(diff) > 5:
                self.audit.log("balance_reconciled", "WARN", difference=diff)
            if not acct.can_trade:
                broker_ok, broker_detail = False, "broker says the account cannot trade"
            flat = not any(p.size for p in self.broker.positions()) and not self.broker.open_orders() and self.mgr.active is None
        except (BrokerError, UncertainOrderState) as e:
            broker_ok, broker_detail = False, str(e)
        if not self.mgr.last_reconcile_ok:
            broker_ok, broker_detail = False, f"last reconciliation failed: {self.mgr.last_broker_error or 'state mismatch'}"
        rs = [t["r_multiple"] for t in self.store.trades() if t.get("r_multiple") is not None]
        es, ed = edge_status(rs, self.cfg.risk.edge_min_mean_200) if self.cfg.risk.edge_stop_rules else ("ok", "edge rules off")
        done_today = sum(self.store.traded_session(k) for k in day.trade_keys[:-1])
        losses = 0
        for t in self.store.trades():
            if (t.get("pnl") or 0) < 0:
                losses += 1
            else:
                break
        halts = list(self.mgr.halt_reasons)
        if self.kill.active():
            halts.append(f"kill switch: {self.kill.reason()}")
        entries_ok = self.armed and self.authorized
        ctx = TradeContext(now=now, signal_bar_close=bar_end, max_signal_delay_s=self.cfg.strategy.max_signal_delay_seconds,
                           entries_permitted=entries_ok, halt_reasons=halts,
                           trading_day=self.cal.is_trading_day(key_date(day.key)), early_close=day.early_close,
                           within_entry_window=sig["entry_minute"] < self.params.last_entry_minute,
                           data_ok=not problems, data_detail="; ".join(problems) or "QQQ and MNQ data complete and consistent",
                           broker_ok=broker_ok, broker_detail=broker_detail, flat_and_no_orders=flat,
                           traded_today=done_today >= self.params.max_trades_per_day, contract_ok=day.contract_ok,
                           contract_detail=day.contract_detail, sizing=sizing, account=self.account,
                           max_trade_risk=self.cfg.risk_budget, max_daily_loss=self.cfg.risk.max_daily_loss,
                           max_weekly_loss=self.cfg.risk.max_weekly_loss, max_total_drawdown=self.cfg.risk.max_total_drawdown,
                           safety_reserve=self.cfg.risk.safety_reserve, consecutive_losses=losses,
                           halt_after_consecutive_losses=self.cfg.risk.halt_after_consecutive_losses,
                           edge_status=es, edge_detail=ed, trades_today=done_today,
                           max_trades_per_day=self.params.max_trades_per_day, day_locked=day.locked,
                           max_daily_profit=self.cfg.risk.max_daily_profit, consistency_cap=self.consistency_cap(),
                           planned_gain=sizing.contracts * (sizing.target_ticks * tv - self.cfg.costs.commission_round_turn
                                                            - self.cfg.costs.slippage_ticks_per_side * tv))
        dec = evaluate(ctx)
        day.decision = {**dec.to_dict(), "sizing": sizing.to_dict(), "exec_price": exec_px, "stop_points": stop_pts}
        self.audit.log("risk_decision", "INFO" if dec.allowed else "WARN", allowed=dec.allowed,
                       failed=dec.reasons, contracts=sizing.contracts, stop_ticks=sizing.stop_ticks,
                       risk_per_contract=round(sizing.risk_per_contract, 2), worst_case=round(sizing.worst_case_loss, 2))
        if es == "stop":
            self.mgr.halt(f"edge stop rule: {ed}")
        failed = {n for n, ok, _ in dec.checks if not ok}
        # these two cannot clear by themselves (the account only changes by trading): halt and ask the operator
        for name, why in (("loss_limit_headroom", "account too close to the firm's loss limit for another worst-case loss"),
                          ("personal_drawdown", "personal maximum drawdown reached")):
            if name in failed:
                self.mgr.halt(f"{why}: entries stopped until you decide (reset the account, or adjust limits) "
                              f"and run clear-halts")
        if not dec.allowed:
            tag = f"SKIP-{sig['trade_key']}"
            if self.store.create_intent(tag, sig["trade_key"], {"signal": sig, "reasons": dec.reasons}):
                self.store.update_intent(tag, "skipped")
            self.alert.send(f"{side} signal NOT traded: " + "; ".join(dec.reasons), "INFO", key=f"skip-{sig['trade_key']}")
            day.awaiting["skipped"] = True
            return
        if not self.mgr.submit(sig, sizing, day.contract.id, tick, tv):
            day.awaiting["skipped"] = True

    # ------------------------------------------------------------------ end of day
    def _end_day(self, now: datetime) -> None:
        day = self.day
        while self.engine.s is not None and self.engine.s.next_bar < 78:
            self.engine.complete_bar(self.engine.s.next_bar)
        try:
            final = self._download_session(self.sig_src, day.sig.symbol, day.key)
            source = "re-downloaded final bars"
        except Exception as e:  # noqa: BLE001
            final, source = day.sig, f"live bars (re-download failed: {e})"
        if len(final.bars) < len(day.sig.bars):
            final, source = day.sig, "live bars (re-download had fewer bars)"
        eng2 = NB3V2Engine.restore(day.start_snapshot)
        final_sigs = self._feed_whole_session(eng2, day.key, final)
        self._record_signal_agreement(day, final_sigs[0].to_dict() if final_sigs else None, source)
        self.engine.end_session()
        self.engine = eng2
        self.store.put("engine_snapshot", {"engine": self.engine.snapshot(), "last_session": day.key})
        nxt = self.cal.next_trading_day(key_date(day.key))
        pr = PAYOUT_PRESETS.get(self.cfg.account.payout_rules)
        self.account.end_of_day(new_week=nxt.isocalendar()[1] != key_date(day.key).isocalendar()[1],
                                win_day=pr.win_day if pr else None)
        self.store.put("account", self.account.snapshot())
        if pr and self.cfg.risk.phase == "funded":
            adv = payout_advice(self.account, pr, self.cfg.account.payout_keep_above_floor)
            if adv["eligible"]:
                self.alert.send(f"Payout eligible on {pr.name}: request ${adv['recommended']:,.0f} on the firm's site "
                                f"(about ${adv['to_you_after_split']:,.0f} to you), then run record-payout",
                                "INFO", key=f"payout-{self.account.s.payouts}")
        if self.cfg.risk.phase == "evaluation" and self.account.evaluation_passed():
            self.mgr.halt(f"evaluation target reached (balance ${self.account.s.balance:,.2f}, best day "
                          f"${self.account.s.best_day:,.2f}): the firm should now move you to the funded account. "
                          f"Set risk.phase = funded and the funded account preset, then clear-halts", "INFO")
        day.eod_done = True
        self.audit.log("session_end", session=day.key, history_source=source, bars=len(final.bars),
                       balance=round(self.account.s.balance, 2), floor=round(self.account.s.floor, 2),
                       incomplete_bars=sorted(day.incomplete_bars))

    def _record_signal_agreement(self, day: Day, final: dict | None, source: str) -> None:
        """Did the live data give the same signal as the final (re-downloaded) data? Tracked every day."""
        live = day.signal
        if live is None and final is None:
            kind = "both_none"
        elif live is None:
            kind = "missed_live"
        elif final is None:
            kind = "extra_live"
        else:
            kind = "same" if (live["bar"], live["direction"]) == (final["bar"], final["direction"]) else "different"
        agg = self.store.get("signal_agreement") or {"same": 0, "both_none": 0, "different": 0, "missed_live": 0, "extra_live": 0}
        agg[kind] = agg.get(kind, 0) + 1
        self.store.put("signal_agreement", agg)
        lvl = "INFO" if kind in ("same", "both_none") else "WARN"
        self.audit.log("signal_agreement", lvl, session=day.key, result=kind, final_source=source,
                       live=None if live is None else (live["bar"], live["direction"]),
                       final=None if final is None else (final["bar"], final["direction"]))

    # ------------------------------------------------------------------ emergencies
    def _on_kill(self, reason: str) -> None:
        self.kill_handled = True
        self.set_armed(False, f"kill switch: {reason}")
        self.mgr.halt(f"kill switch: {reason}")
        self.mgr.emergency_flatten(reason)
        self.alert.send(f"KILL SWITCH: {reason}. All orders cancelled, positions closed, bot disarmed.", "CRITICAL")

    # ------------------------------------------------------------------ status for the dashboard
    def _publish_status(self, now: datetime) -> None:
        mono = _time.monotonic()
        if mono - self._last_status < 1.0:             # at most once a second (wall clock)
            return
        self._last_status = mono
        day, t = self.day, self.mgr.active
        trades = self.store.trades(500)
        rs = [x["r_multiple"] for x in trades if x.get("r_multiple") is not None]
        pnl = [x["pnl"] for x in trades if x.get("pnl") is not None]
        es, ed = edge_status(rs, self.cfg.risk.edge_min_mean_200)
        pr = PAYOUT_PRESETS.get(self.cfg.account.payout_rules)
        steady = self.params.max_trades_per_day > 1 or self.params.reward_risk != 3.0
        st = {
            "strategy": {"reward_risk": self.params.reward_risk, "max_trades_per_day": self.params.max_trades_per_day,
                         "firm_max_contracts_now": self.account.max_contracts_now()},
            "payout": (payout_advice(self.account, pr, self.cfg.account.payout_keep_above_floor)
                       if pr and self.cfg.risk.phase == "funded" else None),
            "today_signals": day.signals if day else [],
            "daily_limits": {"loss_limit": self.daily_loss_limit(), "profit_cap": self.cfg.risk.max_daily_profit or None,
                             "consistency_cap": self.consistency_cap(), "locked": day.locked if day else "",
                             "day_pnl": round(self.account.day_pnl(), 2)},
            "profile": self.cfg.bot.profile, "banner": self.cfg.bot.banner,
            "data_sources": {"signal": getattr(self.sig_src, "name", "?"), "execution_prices": getattr(self.exe_src, "name", "?"),
                             "notes": list(getattr(self.sig_src, "notes", []))[-3:]},
            "signal_agreement": self.store.get("signal_agreement"),
            "starting_balance": self.account.r.starting_balance,
            "time_new_york": f"{now.astimezone(NY):%Y-%m-%d %H:%M:%S %Z}",
            "time_zagreb": f"{now.astimezone(ZAGREB):%Y-%m-%d %H:%M:%S %Z}",
            "mode": self.mode, "armed": self.armed, "authorized": self.authorized, "authorization": self.auth_detail,
            "kill_switch": self.kill.active(), "halts": self.mgr.halt_reasons, "broker": self.broker.name,
            "broker_error": self.mgr.last_broker_error, "reconcile_ok": self.mgr.last_reconcile_ok,
            "session": day.key if day else None, "early_close": day.early_close if day else None,
            "contract": day.contract_detail if day else None,
            "engine_warm": bool(self.engine and self.engine.warm()),
            "data": {"signal_bars": len(day.sig.bars) if day else 0, "exec_bars": len(day.exe.bars) if day else 0,
                     "incomplete_bars": sorted(day.incomplete_bars) if day else [],
                     "errors": day.data_errors[-5:] if day else [],
                     "last_bar_new_york": (f"{minute_start(day.key, max(day.sig.bars)).astimezone(NY):%H:%M}"
                                           if day and day.sig.bars else None)},
            "today_signal": day.signal if day else None, "today_decision": day.decision if day else None,
            "active_trade": None if t is None else {k: getattr(t, k) for k in ("tag", "state", "side", "size", "fill_price",
                                                                                 "stop_price", "target_price", "exit_reason")},
            "account": {"balance": round(self.account.s.balance, 2), "equity": round(self.account.equity, 2),
                        "floor": round(self.account.s.floor, 2), "remaining_allowance": round(self.account.remaining_allowance(), 2),
                        "day_pnl": round(self.account.day_pnl(), 2), "rules": self.account.r.name},
            "performance": {"trades": len(rs), "mean_r": round(sum(rs) / len(rs), 3) if rs else None,
                            "win_rate": round(sum(r > 0 for r in rs) / len(rs), 3) if rs else None,
                            "total_pnl": round(sum(pnl), 2), "edge_status": es, "edge_detail": ed,
                            "backtest_reference": ("research 2023-26: +0.09R/trade, ~1.45 trades/day (1.5R, up to 2/day); "
                                                   "2016-22: +0.07R" if steady else
                                                   "holdout +0.255R/trade, 48% winners, ~0.86 trades/day")},
            "recent_trades": trades[:20], "alerts": self.alert.sent[-15:],
        }
        with self.status_lock:
            self.status = st


def key_date(key: int) -> date:
    return date(key // 10000, key // 100 % 100, key % 100)
