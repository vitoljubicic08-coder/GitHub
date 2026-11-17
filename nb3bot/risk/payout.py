"""Payout eligibility and a recommended request (the bot never requests payouts: you do, on the firm's site).

LucidFlex 50K (help centre, checked 2026-11-17): a payout needs 5 days with at least $150 profit in the
current cycle and a positive net profit in the cycle; it may be up to 50% of the profit and at most $2,000,
at least $500; 90% goes to the trader; after a payout the loss limit locks at $50,100; after 5 payouts the
account moves to live. Research round 5 (backtest/RESULTS_5.md): requesting as soon as eligible while
keeping at least $500 above the post-payout loss limit got the most accounts paid.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PayoutRules:
    name: str
    win_day: float
    win_days: int
    fraction: float
    cap: float
    minimum: float
    floor_after: float          # loss-limit balance after a payout
    max_payouts: int
    split: float


PAYOUT_PRESETS = {
    "lucid_flex_50k": PayoutRules("LucidFlex 50K", 150.0, 5, 0.5, 2000.0, 500.0, 50100.0, 5, 0.9),
}


def advice(account, rules: PayoutRules, keep_above_floor: float) -> dict:
    s, start = account.s, account.r.starting_balance
    profit = s.balance - start
    reasons = []
    if s.cycle_win_days < rules.win_days:
        reasons.append(f"{s.cycle_win_days} of {rules.win_days} days with at least ${rules.win_day:,.0f} profit")
    if s.cycle_profit <= 0:
        reasons.append("no net profit in this payout cycle yet")
    if s.payouts >= rules.max_payouts:
        reasons.append(f"{rules.max_payouts} payouts taken: the firm moves the account to live")
    largest = max(0.0, min(rules.fraction * profit, rules.cap))
    recommended = max(0.0, min(largest, s.balance - rules.floor_after - keep_above_floor))
    if not reasons and recommended < rules.minimum:
        reasons.append(f"recommended amount ${recommended:,.0f} is below the ${rules.minimum:,.0f} minimum "
                       f"(keeping ${keep_above_floor:,.0f} above the ${rules.floor_after:,.0f} loss limit)")
    eligible = not reasons
    return {"rules": rules.name, "eligible": eligible, "reasons": reasons, "profit": round(profit, 2),
            "cycle_win_days": s.cycle_win_days, "cycle_profit": round(s.cycle_profit, 2), "payouts_taken": s.payouts,
            "largest_allowed": round(largest, 2), "recommended": round(recommended, 2) if eligible else 0.0,
            "to_you_after_split": round(recommended * rules.split, 2) if eligible else 0.0,
            "loss_limit_after": rules.floor_after}
