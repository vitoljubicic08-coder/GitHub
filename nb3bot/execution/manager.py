"""Trade execution manager: one NB3 V2 trade per session, from signal to recorded result.

States: SUBMITTING -> WORKING (entry sent) -> PROTECTING (filled, checking stop/target) -> OPEN
        -> EXITING (15:55 flatten or emergency) -> closed and recorded.
        UNCERTAIN: the entry request got no reliable answer; the order is looked up by its unique tag
        (never resent).
Safety rules enforced here:
  * an intent is stored in the database BEFORE the order is sent; one intent per session, so no signal
    can produce a second entry (retries, restarts, duplicate messages);
  * every fill must be protected: the broker-side bracket is verified; if the stop is missing the bot
    places one; if that fails it closes the position;
  * at 15:55 New York the bot cancels the target, closes the position and cancels the stop, then checks
    that nothing is left (no orphaned orders);
  * the trade's P&L comes from the broker's own fill records.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from nb3bot.broker.base import BracketEntry, Broker, BrokerError, BrokerUnavailable, UncertainOrderState
from nb3bot.timeutil import NY


@dataclass
class ActiveTrade:
    tag: str
    session: int
    side: int
    size: int
    stop_ticks: int
    target_ticks: int
    tick_size: float
    tick_value: float
    contract_id: str
    planned_loss: float
    signal: dict
    submitted_at: str
    state: str = "SUBMITTING"
    entry_order_id: str | None = None
    fill_price: float | None = None
    fill_time: str | None = None
    filled_size: int = 0
    stop_price: float | None = None
    target_price: float | None = None
    stop_order_id: str | None = None
    target_order_id: str | None = None
    protect_since: str | None = None
    exit_requested_at: str | None = None
    exit_reason: str | None = None
    notes: list = field(default_factory=list)

    @property
    def submitted(self) -> datetime:
        return datetime.fromisoformat(self.submitted_at)


class TradeManager:
    def __init__(self, broker: Broker, store, audit, alerter, account, cfg, clock):
        self.b = broker
        self.store = store
        self.audit = audit
        self.alert = alerter
        self.acc = account
        self.cfg = cfg
        self.clock = clock
        snap = store.get("active_trade")
        self.active: ActiveTrade | None = ActiveTrade(**snap) if snap else None
        self.halt_reasons: list[str] = store.get("halt_reasons", [])
        self.last_reconcile_ok = True
        self.last_broker_error = ""
        # flatten at 15:55 plus the bar grace period, so the 15:54 bar is known (the backtest exits at its close)
        self.eod_delay_s = cfg.data.bar_grace_seconds + 1.0

    # ------------------------------------------------------------------ persistence helpers
    def _save(self) -> None:
        self.store.put("active_trade", asdict(self.active) if self.active else None)

    def halt(self, reason: str, level: str = "CRITICAL") -> None:
        if reason not in self.halt_reasons:
            self.halt_reasons.append(reason)
            self.store.put("halt_reasons", self.halt_reasons)
            self.audit.log("halt", level, reason=reason)
            self.alert.send(f"Trading halted: {reason}", level)

    def clear_halts(self) -> None:
        self.halt_reasons = []
        self.store.put("halt_reasons", [])

    # ------------------------------------------------------------------ entry
    def submit(self, signal: dict, sizing, contract_id: str, tick_size: float, tick_value: float) -> bool:
        now = self.clock.now()
        tag = f"NB3V2-{signal['session']}-{self.cfg.broker.account_id or 'paper'}"
        t = ActiveTrade(tag, signal["session"], signal["direction"], sizing.contracts, sizing.stop_ticks,
                        sizing.target_ticks, tick_size, tick_value, contract_id, sizing.planned_loss, signal,
                        now.isoformat())
        if not self.store.create_intent(tag, signal["session"], {"signal": signal, "sizing": sizing.to_dict()}):
            self.audit.log("duplicate_signal_blocked", "WARN", session=signal["session"], tag=tag)
            return False
        self.active = t
        self._save()
        req = BracketEntry(contract_id, t.side, t.size, t.stop_ticks, t.target_ticks, tag)
        self.audit.log("entry_submit", side="BUY" if t.side > 0 else "SELL", size=t.size, stop_ticks=t.stop_ticks,
                       target_ticks=t.target_ticks, contract=contract_id, tag=tag)
        try:
            t.entry_order_id = self.b.place_bracket_entry(req)
            t.state = "WORKING"
            self.store.update_intent(tag, "working", t.entry_order_id)
        except UncertainOrderState as e:
            t.state = "UNCERTAIN"
            t.notes.append(str(e))
            self.store.update_intent(tag, "uncertain")
            self.alert.send(f"Entry {tag}: no reliable broker answer ({e}); checking by tag, NOT resending", "WARN")
        except BrokerError as e:
            self.store.update_intent(tag, "rejected", error=str(e))
            self.alert.send(f"Entry {tag} rejected: {e}", "WARN")
            self.active = None
        self._save()
        return self.active is not None

    # ------------------------------------------------------------------ main state machine
    def tick(self) -> None:
        t = self.active
        if t is None:
            return
        now = self.clock.now()
        try:
            {"UNCERTAIN": self._uncertain, "WORKING": self._working, "PROTECTING": self._protecting,
             "OPEN": self._open, "EXITING": self._exiting}.get(t.state, lambda *_: None)(t, now)
            self.last_broker_error = ""
        except (UncertainOrderState, BrokerUnavailable) as e:
            self.last_broker_error = str(e)
            self.audit.log("broker_unreachable", "WARN", state=t.state, error=str(e))
        if self.active is not None:
            self._save()

    def _uncertain(self, t: ActiveTrade, now: datetime) -> None:
        o = self.b.find_order_by_tag(t.tag, t.submitted - timedelta(minutes=1))
        if o is not None:
            t.entry_order_id, t.state = o.id, "WORKING"
            self.store.update_intent(t.tag, "working", o.id)
            self.audit.log("entry_found_by_tag", tag=t.tag, order_id=o.id, status=o.status)
            return
        if (now - t.submitted).total_seconds() > 60:
            pos = [p for p in self.b.positions() if p.contract_id == t.contract_id and p.size]
            if pos:
                t.fill_price, t.filled_size, t.state = pos[0].avg_price, abs(pos[0].size), "PROTECTING"
                t.fill_time, t.protect_since = now.isoformat(), now.isoformat()
                self._set_bracket_prices(t)
                self.alert.send(f"Entry {t.tag}: order not found by tag but a position exists; protecting it", "CRITICAL")
            else:
                self.store.update_intent(t.tag, "not_placed")
                self.audit.log("entry_not_placed", "WARN", tag=t.tag)
                self.alert.send(f"Entry {t.tag} was not placed (verified: no order, no position). Signal skipped.", "WARN")
                self.active = None
                self._save()

    def _set_bracket_prices(self, t: ActiveTrade) -> None:
        t.stop_price = round(t.fill_price - t.side * t.stop_ticks * t.tick_size, 10)
        t.target_price = round(t.fill_price + t.side * t.target_ticks * t.tick_size, 10)

    def _working(self, t: ActiveTrade, now: datetime) -> None:
        o = self.b.order(t.entry_order_id, t.submitted - timedelta(minutes=1))
        if o is not None and o.status == "filled":
            t.fill_price, t.filled_size = float(o.fill_price), o.filled_size or t.size
            t.fill_time, t.protect_since, t.state = now.isoformat(), now.isoformat(), "PROTECTING"
            self._set_bracket_prices(t)
            self.store.update_intent(t.tag, "filled", fill_price=t.fill_price)
            self.audit.log("entry_filled", tag=t.tag, price=t.fill_price, size=t.filled_size,
                           stop=t.stop_price, target=t.target_price)
            self.alert.send(f"FILLED {'BUY' if t.side > 0 else 'SELL'} {t.filled_size} {t.contract_id} @ {t.fill_price} "
                            f"stop {t.stop_price} target {t.target_price}", "INFO", key=f"fill-{t.tag}")
            return
        if o is not None and o.status in ("rejected", "cancelled", "expired"):
            self.store.update_intent(t.tag, "rejected", status=o.status)
            self.alert.send(f"Entry {t.tag} ended without a fill ({o.status})", "WARN")
            self.active = None
            self._save()
            return
        # the paper broker fills at the next 1-minute bar's open (as the backtest), so it can take ~65 s
        timeout = self.cfg.broker.fill_timeout_seconds if self.b.places_real_orders else 90.0
        if (now - t.submitted).total_seconds() > timeout:
            if o is not None and o.filled_size > 0:
                self.b.cancel(o.id)
                t.fill_price, t.filled_size = float(o.fill_price), o.filled_size
                t.fill_time, t.protect_since, t.state = now.isoformat(), now.isoformat(), "PROTECTING"
                self._set_bracket_prices(t)
                self.alert.send(f"Entry {t.tag} partially filled ({o.filled_size}/{t.size}); rest cancelled", "WARN")
                return
            try:
                if o is not None:
                    self.b.cancel(o.id)
            except BrokerError:
                pass
            o2 = self.b.order(t.entry_order_id, t.submitted - timedelta(minutes=1))
            if o2 is not None and o2.status == "filled":
                return                                   # filled while cancelling: handled next tick
            pos = [p for p in self.b.positions() if p.contract_id == t.contract_id and p.size]
            if pos:
                return
            self.store.update_intent(t.tag, "not_filled")
            self.alert.send(f"Entry {t.tag} not filled within {timeout:.0f}s; cancelled", "WARN")
            self.active = None
            self._save()

    def _protective(self, t: ActiveTrade) -> tuple[list, list]:
        oo = [o for o in self.b.open_orders() if o.contract_id == t.contract_id and o.side == -t.side]
        stops = [o for o in oo if o.type in ("stop", "stop_limit", "trailing")]
        targets = [o for o in oo if o.type == "limit"]
        return stops, targets

    def _protecting(self, t: ActiveTrade, now: datetime) -> None:
        pos = [p for p in self.b.positions() if p.contract_id == t.contract_id and p.size]
        if not pos:                                      # already stopped or target hit
            t.state = "OPEN"
            self._open(t, now)
            return
        size = abs(pos[0].size)
        stops, targets = self._protective(t)
        stop_ok = stops and sum(o.size for o in stops) == size
        if stop_ok and targets:
            t.stop_order_id, t.target_order_id, t.state = stops[0].id, targets[0].id, "OPEN"
            self.audit.log("protected", tag=t.tag, stop_order=stops[0].id, stop_price=stops[0].stop_price,
                           target_order=targets[0].id, target_price=targets[0].limit_price)
            return
        waited = (now - datetime.fromisoformat(t.protect_since)).total_seconds()
        if waited < self.cfg.broker.bracket_check_seconds:
            return
        if stops and not stop_ok:
            self.alert.send(f"{t.tag}: stop size {sum(o.size for o in stops)} does not match position {size}; flattening", "CRITICAL")
            self.flatten(t, "SIZE_MISMATCH")
            return
        try:
            if not stops:
                t.stop_order_id = self.b.place_stop(t.contract_id, -t.side, size, t.stop_price, f"{t.tag}-SL")
                self.alert.send(f"{t.tag}: bracket stop missing after {waited:.0f}s; placed stop {t.stop_price}", "CRITICAL")
            else:
                t.stop_order_id = stops[0].id
            if not targets:
                t.target_order_id = self.b.place_limit(t.contract_id, -t.side, size, t.target_price, f"{t.tag}-TP")
                self.alert.send(f"{t.tag}: bracket target missing; placed target {t.target_price}", "WARN")
            else:
                t.target_order_id = targets[0].id
            t.state = "OPEN"
            t.notes.append("protection placed by bot")
        except (BrokerError, UncertainOrderState) as e:
            self.alert.send(f"{t.tag}: could not place protective stop ({e}); CLOSING the position", "CRITICAL")
            self.flatten(t, "PROTECTION_FAILED")

    def _open(self, t: ActiveTrade, now: datetime) -> None:
        pos = [p for p in self.b.positions() if p.contract_id == t.contract_id and p.size]
        if not pos:
            self._finalize(t, now)
            return
        ny = now.astimezone(NY)
        eod = ny.replace(hour=15, minute=55, second=0, microsecond=0) + timedelta(seconds=self.eod_delay_s)
        if ny >= eod:
            self.flatten(t, "EOD")
            return
        stops, _ = self._protective(t)
        if not stops:
            t.state, t.protect_since = "PROTECTING", (now - timedelta(seconds=self.cfg.broker.bracket_check_seconds)).isoformat()
            self.alert.send(f"{t.tag}: position open without a stop order; restoring protection", "CRITICAL")

    def flatten(self, t: ActiveTrade, reason: str) -> None:
        """Cancel the target, close the position, cancel the stop; verified in EXITING."""
        now = self.clock.now()
        t.exit_reason = t.exit_reason or reason
        t.exit_requested_at = now.isoformat()
        t.state = "EXITING"
        self._save()
        for oid in (t.target_order_id,):
            if oid:
                try:
                    self.b.cancel(oid)
                except BrokerError:
                    pass
        try:
            if any(p.contract_id == t.contract_id and p.size for p in self.b.positions()):
                self.b.close_position(t.contract_id)
        except BrokerError as e:
            self.alert.send(f"{t.tag}: close request failed ({e}); retrying", "CRITICAL")
        self._cancel_all(t.contract_id)
        self.audit.log("flatten", tag=t.tag, reason=reason)

    def _cancel_all(self, contract_id: str | None = None) -> int:
        n = 0
        for o in self.b.open_orders():
            if contract_id is None or o.contract_id == contract_id:
                try:
                    self.b.cancel(o.id)
                    n += 1
                except BrokerError as e:
                    self.audit.log("cancel_failed", "WARN", order=o.id, error=str(e))
        return n

    def _exiting(self, t: ActiveTrade, now: datetime) -> None:
        pos = [p for p in self.b.positions() if p.contract_id == t.contract_id and p.size]
        if pos:
            if (now - datetime.fromisoformat(t.exit_requested_at)).total_seconds() > 5:
                self.alert.send(f"{t.tag}: still not flat after close request; closing again", "CRITICAL")
                try:
                    self.b.close_position(t.contract_id)
                except BrokerError as e:
                    self.audit.log("close_retry_failed", "CRITICAL", error=str(e))
                t.exit_requested_at = now.isoformat()
            return
        left = self._cancel_all(t.contract_id)
        if left:
            self.audit.log("orphans_cancelled", "WARN", count=left)
        self._finalize(t, now)

    # ------------------------------------------------------------------ results
    def _finalize(self, t: ActiveTrade, now: datetime) -> None:
        self._cancel_all(t.contract_id)
        fills = [f for f in self.b.fills(t.submitted - timedelta(minutes=1)) if f.contract_id == t.contract_id and not f.voided]
        gross = sum(f.pnl for f in fills if f.pnl is not None)
        fees = sum(f.fees for f in fills)
        pnl = gross - fees
        closing = [f for f in fills if f.pnl is not None]
        exit_px = (sum(f.price * f.size for f in closing) / sum(f.size for f in closing)) if closing else math.nan
        reason = t.exit_reason
        if reason is None:
            ids = {f.order_id for f in closing}
            reason = "TARGET" if t.target_order_id in ids else "STOP" if t.stop_order_id in ids else "OTHER"
        one_r = (t.filled_size or t.size) * t.stop_ticks * t.tick_value
        r_mult = pnl / one_r if one_r else math.nan
        rec = {"tag": t.tag, "side": "BUY" if t.side > 0 else "SELL", "size": t.filled_size or t.size,
               "contract": t.contract_id, "fill_price": t.fill_price, "fill_time": t.fill_time, "stop_price": t.stop_price,
               "target_price": t.target_price, "exit_price": exit_px, "exit_time": now.isoformat(), "exit_reason": reason,
               "gross_pnl": gross, "fees": fees, "planned_loss": t.planned_loss, "signal": t.signal, "notes": t.notes}
        self.store.record_trade(t.session, t.tag, rec, pnl, r_mult)
        self.store.update_intent(t.tag, "closed", pnl=pnl)
        self.acc.realize(pnl)
        self.audit.log("trade_closed", tag=t.tag, reason=reason, pnl=round(pnl, 2), r=round(r_mult, 3))
        self.alert.send(f"CLOSED {rec['side']} {rec['size']} {t.contract_id}: {reason}, P&L {pnl:+.2f} ({r_mult:+.2f}R)",
                        "INFO", key=f"close-{t.tag}")
        self.active = None
        self._save()

    # ------------------------------------------------------------------ reconciliation and emergencies
    def reconcile(self, contract_ids: list[str], flatten_unknown: bool = True) -> bool:
        """Compare broker positions/orders with the bot's own state. Returns True if consistent."""
        try:
            pos = [p for p in self.b.positions() if p.size]
            orders = self.b.open_orders()
        except (BrokerError, UncertainOrderState) as e:
            self.last_reconcile_ok = False
            self.last_broker_error = str(e)
            return False
        ok = True
        t = self.active
        mine = {t.contract_id} if t else set()
        for p in pos:
            if p.contract_id not in mine:
                ok = False
                self.halt(f"unknown position {p.size} {p.contract_id} found at the broker")
                if flatten_unknown:
                    try:
                        self.b.close_position(p.contract_id)
                        self.audit.log("unknown_position_closed", "CRITICAL", contract=p.contract_id, size=p.size)
                    except BrokerError as e:
                        self.audit.log("unknown_position_close_failed", "CRITICAL", error=str(e))
        stray = [o for o in orders if o.contract_id not in mine]    # no trade owns them: orphans
        if stray:
            ok = False
            for o in stray:
                try:
                    self.b.cancel(o.id)
                except BrokerError:
                    pass
            self.audit.log("orphan_orders_cancelled", "WARN", count=len(stray))
        if t is not None and t.state == "OPEN":
            p = [x for x in pos if x.contract_id == t.contract_id]
            if p and abs(p[0].size) != (t.filled_size or t.size):
                ok = False
                self.alert.send(f"{t.tag}: broker position {p[0].size} differs from expected {t.filled_size}; flattening", "CRITICAL")
                self.flatten(t, "RECONCILE_MISMATCH")
        self.last_reconcile_ok = ok
        return ok

    def emergency_flatten(self, reason: str) -> None:
        """Kill switch: cancel every order and close every position, whatever the state."""
        self.audit.log("emergency_flatten", "CRITICAL", reason=reason)
        try:
            self._cancel_all(None)
            for p in self.b.positions():
                if p.size:
                    self.b.close_position(p.contract_id)
            self._cancel_all(None)
        except (BrokerError, UncertainOrderState) as e:
            self.alert.send(f"EMERGENCY FLATTEN INCOMPLETE ({e}). Check the platform manually NOW.", "CRITICAL")
            return
        if self.active is not None:
            self.active.exit_reason = self.active.exit_reason or f"KILL: {reason}"
            self.active.state = "EXITING"
            self.active.exit_requested_at = self.clock.now().isoformat()
            self._save()
