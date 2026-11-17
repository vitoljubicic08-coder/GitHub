"""Pre-trade risk guard: every check must pass before an entry order is sent.

The guard never changes the strategy's trade; it can only veto it. Every decision is returned with the
full list of checks (name, passed, detail) and written to the audit log.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from nb3bot.risk.account import AccountTracker
from nb3bot.risk.sizing import SizingResult


@dataclass
class Decision:
    allowed: bool
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        return [f"{n}: {d}" for n, ok, d in self.checks if not ok]

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "checks": [{"check": n, "ok": ok, "detail": d} for n, ok, d in self.checks]}


@dataclass
class TradeContext:
    now: datetime
    signal_bar_close: datetime
    max_signal_delay_s: float
    entries_permitted: bool            # armed, not killed, mode allows entries
    halt_reasons: list[str]
    trading_day: bool
    early_close: bool
    within_entry_window: bool          # before minute 330 and market open
    data_ok: bool
    data_detail: str
    broker_ok: bool
    broker_detail: str
    flat_and_no_orders: bool
    traded_today: bool
    contract_ok: bool
    contract_detail: str
    sizing: SizingResult
    account: AccountTracker
    max_trade_risk: float
    max_daily_loss: float
    max_weekly_loss: float
    max_total_drawdown: float
    safety_reserve: float
    consecutive_losses: int
    halt_after_consecutive_losses: int
    edge_status: str                   # ok | pause | stop
    edge_detail: str
    trades_today: int = 0
    max_trades_per_day: int = 1
    day_locked: str = ""               # daily loss / profit lockout reason ("" = not locked)
    max_daily_profit: float = 0.0      # 0 = off
    consistency_cap: float | None = None   # evaluation best-day cap in $ (rule x profit target)
    planned_gain: float = 0.0          # the trade's profit at its full target, after costs


def evaluate(c: TradeContext) -> Decision:
    ch: list[tuple[str, bool, str]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        ch.append((name, bool(ok), detail))

    age = (c.now - c.signal_bar_close).total_seconds()
    add("armed", c.entries_permitted, "entries are enabled" if c.entries_permitted else "bot is not armed for entries")
    add("no_halt", not c.halt_reasons, "; ".join(c.halt_reasons) or "none")
    add("trading_day", c.trading_day, "exchange trading day" if c.trading_day else "exchange holiday or weekend")
    add("not_early_close", not c.early_close,
        "early-close session: NB3 V2 defines no rule for it, the bot does not trade" if c.early_close else "full session")
    add("entry_window", c.within_entry_window, "signal bar opened 09:30-14:50 and market open")
    add("signal_fresh", 0 <= age <= c.max_signal_delay_s, f"{age:.1f}s after the 5-minute bar closed (max {c.max_signal_delay_s:.0f}s)")
    add("trades_per_day", not c.traded_today,
        f"already {c.trades_today} trade(s) this session (limit {c.max_trades_per_day})" if c.traded_today
        else f"trade {c.trades_today + 1} of at most {c.max_trades_per_day} today")
    add("market_data", c.data_ok, c.data_detail)
    add("broker", c.broker_ok, c.broker_detail)
    add("flat", c.flat_and_no_orders, "no open position and no working orders" if c.flat_and_no_orders else "position or orders already open")
    add("contract", c.contract_ok, c.contract_detail)
    s = c.sizing
    add("size", s.contracts >= 1, s.reason or f"{s.contracts} contract(s), ${s.risk_per_contract:,.2f} risk each")
    add("max_trade_risk", s.planned_loss <= c.max_trade_risk + 1e-9,
        f"planned loss ${s.planned_loss:,.2f} vs limit ${c.max_trade_risk:,.2f}")
    acc = c.account
    room = acc.remaining_allowance() - s.worst_case_loss
    add("loss_limit_headroom", room >= c.safety_reserve,
        f"equity ${acc.equity:,.2f}, firm floor ${acc.s.floor:,.2f}, worst case ${s.worst_case_loss:,.2f}, "
        f"left ${room:,.2f} (reserve ${c.safety_reserve:,.0f})")
    dll = acc.r.daily_loss_limit
    if dll:
        left = dll + acc.day_pnl() - s.worst_case_loss
        add("firm_daily_limit", left >= 0, f"firm daily limit ${dll:,.0f}, today {acc.day_pnl():+,.2f}, left after worst case ${left:,.2f}")
    add("personal_daily_loss", acc.day_pnl() - s.worst_case_loss >= -c.max_daily_loss,
        f"today {acc.day_pnl():+,.2f}, limit -${c.max_daily_loss:,.0f}")
    add("day_lockout", not c.day_locked, c.day_locked or "no daily lockout")
    if c.max_daily_profit > 0:
        add("daily_profit_cap", acc.day_pnl() < c.max_daily_profit,
            f"today {acc.day_pnl():+,.2f}, daily profit cap ${c.max_daily_profit:,.0f}")
    if c.consistency_cap is not None:
        add("consistency_day_cap", acc.day_pnl() + c.planned_gain <= c.consistency_cap,
            f"today {acc.day_pnl():+,.2f} + this trade's full target ${c.planned_gain:,.2f} vs best-day cap "
            f"${c.consistency_cap:,.0f}")
    add("personal_weekly_loss", acc.week_pnl() - s.worst_case_loss >= -c.max_weekly_loss,
        f"this week {acc.week_pnl():+,.2f}, limit -${c.max_weekly_loss:,.0f}")
    add("personal_drawdown", acc.drawdown_from_hwm() + s.worst_case_loss <= c.max_total_drawdown,
        f"drawdown from high ${acc.drawdown_from_hwm():,.2f}, limit ${c.max_total_drawdown:,.0f}")
    if c.halt_after_consecutive_losses > 0:
        add("consecutive_losses", c.consecutive_losses < c.halt_after_consecutive_losses,
            f"{c.consecutive_losses} losses in a row (limit {c.halt_after_consecutive_losses})")
    add("edge_monitor", c.edge_status == "ok", c.edge_detail)
    ok = all(x[1] for x in ch) and not math.isnan(s.risk_per_contract)
    return Decision(ok, ch)


def edge_status(r_multiples: list[float], min_mean_200: float = 0.05) -> tuple[str, str]:
    """Pre-registered stop rules from the research report (per-trade R standard deviation ~1.42):
    pause if mean < -0.13R after 50 trades; stop if mean < -0.04R after 100; stop if mean < +0.05R after 200
    (`min_mean_200`; the Lucid steady profile uses 0, its expected mean is only about +0.07-0.10R)."""
    n = len(r_multiples)
    if n == 0:
        return "ok", "no live trades yet"
    m = sum(r_multiples) / n
    if n >= 200 and m < min_mean_200:
        return "stop", f"mean {m:+.3f}R after {n} trades is below {min_mean_200:+.2f}R (200-trade rule)"
    if n >= 100 and m < -0.04:
        return "stop", f"mean {m:+.3f}R after {n} trades is below -0.04R (100-trade rule)"
    if n >= 50 and m < -0.13:
        return "pause", f"mean {m:+.3f}R after {n} trades is below -0.13R (50-trade rule): review before continuing"
    return "ok", f"mean {m:+.3f}R over {n} trades"
