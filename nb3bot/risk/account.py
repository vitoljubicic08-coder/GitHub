"""Prop-firm account tracker: balance, high-water mark, loss-limit floor, remaining allowance.

Rule types (from the firms' rule pages, checked 2026-11-17; see docs/bot/RISK_RULES.md):
  eod       floor = highest END-OF-DAY balance - max loss, never moves down, stops at
            starting balance + lock_profit; breached IN REAL TIME by balance + unrealised P&L
            (Topstep, Lucid Flex, Tradeify Growth).
  intraday  floor also trails the highest balance INCLUDING unrealised profit, tick by tick
            (Apex-style, Take Profit Trader PRO). The bot updates it from every price mark it sees,
            which can lag the firm's own tick-level calculation, so the safety reserve matters more.
  static    floor = starting balance - max loss, never moves.
The firm's own calculation is authoritative; this tracker exists so the bot stops BEFORE the limit.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class FirmRules:
    name: str
    starting_balance: float
    max_loss: float
    trailing: str                       # eod | intraday | static
    lock_profit: float | None           # None = keeps trailing
    daily_loss_limit: float | None      # firm's daily limit (soft at the firms modelled), None = none
    max_contracts: int
    profit_target: float | None = None  # evaluation target (None for funded accounts)
    consistency: float | None = None    # best day must be <= this share of total profit to pass


PRESETS: dict[str, FirmRules] = {
    "topstep_combine_50k": FirmRules("Topstep 50K Trading Combine", 50000, 2000, "eod", 0.0, 1000, 50, 3000.0, 0.55),
    "topstep_xfa_50k": FirmRules("Topstep 50K Express Funded", 0, 2000, "eod", 0.0, 1000, 50),
    "lucid_flex_50k_eval": FirmRules("LucidFlex 50K evaluation", 50000, 2000, "eod", 100.0, None, 40, 3000.0, 0.40),
    "lucid_flex_50k_funded": FirmRules("LucidFlex 50K funded", 50000, 2000, "eod", 100.0, None, 40),
    "tradeify_growth_50k_eval": FirmRules("Tradeify Growth 50K evaluation", 50000, 2000, "eod", None, 1250, 40, 3000.0, None),
    "tradeify_growth_50k_funded": FirmRules("Tradeify Growth 50K funded", 50000, 2000, "eod", 100.0, 1250, 40),
}


@dataclass
class AccountState:
    balance: float
    hwm_eod: float
    hwm_intraday: float
    floor: float
    day_start_balance: float
    week_start_balance: float
    unrealized: float = 0.0
    fixed_floor: float | None = None      # e.g. Topstep sets the floor to $0 after a payout
    best_day: float = 0.0                 # largest single-day profit (consistency rules)
    history: list = field(default_factory=list)


class AccountTracker:
    def __init__(self, rules: FirmRules, state: AccountState | None = None):
        self.r = rules
        b = rules.starting_balance
        self.s = state or AccountState(balance=b, hwm_eod=b, hwm_intraday=b, floor=b - rules.max_loss,
                                       day_start_balance=b, week_start_balance=b)
        self._recompute_floor()

    # ------------------------------------------------------------------ updates
    def _cap(self, f: float) -> float:
        if self.r.lock_profit is not None:
            f = min(f, self.r.starting_balance + self.r.lock_profit)
        return f

    def _recompute_floor(self) -> None:
        if self.s.fixed_floor is not None:
            self.s.floor = self.s.fixed_floor
            return
        if self.r.trailing == "static":
            new = self.r.starting_balance - self.r.max_loss
        elif self.r.trailing == "intraday":
            new = self._cap(self.s.hwm_intraday - self.r.max_loss)
        else:
            new = self._cap(self.s.hwm_eod - self.r.max_loss)
        self.s.floor = max(self.s.floor, new) if not math.isnan(self.s.floor) else new

    def mark(self, unrealized: float) -> None:
        """Latest unrealised P&L of the open position (0 when flat)."""
        self.s.unrealized = unrealized
        if self.r.trailing == "intraday":
            self.s.hwm_intraday = max(self.s.hwm_intraday, self.s.balance + unrealized)
            self._recompute_floor()

    def realize(self, pnl_after_fees: float) -> None:
        self.s.balance += pnl_after_fees
        self.s.unrealized = 0.0
        if self.r.trailing == "intraday":
            self.s.hwm_intraday = max(self.s.hwm_intraday, self.s.balance)
            self._recompute_floor()

    def end_of_day(self, new_week: bool = False) -> None:
        self.s.best_day = max(self.s.best_day, self.s.balance - self.s.day_start_balance)
        self.s.hwm_eod = max(self.s.hwm_eod, self.s.balance)
        self._recompute_floor()
        self.s.history.append({"balance": self.s.balance, "floor": self.s.floor})
        self.s.history = self.s.history[-400:]
        self.s.day_start_balance = self.s.balance
        if new_week:
            self.s.week_start_balance = self.s.balance

    def payout(self, amount: float, floor_after: float | None) -> None:
        """Record a withdrawal; floor_after = firm rule (Topstep XFA: 0) or None (unchanged)."""
        self.s.balance -= amount
        if floor_after is not None:
            self.s.fixed_floor = floor_after
        self._recompute_floor()

    def reconcile_balance(self, broker_balance: float, tolerance: float = 5.0) -> float:
        """Adopt the broker's balance as the truth; return the difference found."""
        diff = broker_balance - self.s.balance
        if abs(diff) > tolerance:
            self.s.balance = broker_balance
        return diff

    # ------------------------------------------------------------------ queries
    def evaluation_passed(self) -> bool:
        """Profit target reached and (if the firm has one) the consistency rule met."""
        t = self.r.profit_target
        if not t:
            return False
        profit = self.s.balance - self.r.starting_balance
        return profit >= t and (self.r.consistency is None or self.s.best_day <= self.r.consistency * profit)

    @property
    def equity(self) -> float:
        return self.s.balance + self.s.unrealized

    def remaining_allowance(self) -> float:
        """Distance from current equity to the firm's loss-limit floor."""
        return self.equity - self.s.floor

    def day_pnl(self) -> float:
        return self.equity - self.s.day_start_balance

    def week_pnl(self) -> float:
        return self.equity - self.s.week_start_balance

    def drawdown_from_hwm(self) -> float:
        return max(self.s.hwm_eod, self.s.hwm_intraday) - self.equity

    def snapshot(self) -> dict:
        return {"rules": asdict(self.r), "state": asdict(self.s), "equity": self.equity,
                "remaining_allowance": self.remaining_allowance(), "day_pnl": self.day_pnl()}

    @classmethod
    def restore(cls, snap: dict) -> "AccountTracker":
        st = AccountState(**snap["state"])
        return cls(FirmRules(**snap["rules"]), st)


def rules_from_config(acc) -> FirmRules:
    if acc.preset != "custom":
        if acc.preset not in PRESETS:
            raise ValueError(f"unknown account preset {acc.preset}; options: {', '.join(PRESETS)} or custom")
        return PRESETS[acc.preset]
    return FirmRules("custom", acc.starting_balance, acc.max_loss_limit, acc.trailing, acc.lock_profit,
                     acc.daily_loss_limit, acc.max_contracts_firm)
