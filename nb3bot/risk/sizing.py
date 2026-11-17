"""Position sizing in whole contracts.

  stop_points        = signal stop distance converted to MNQ points
                       (qqq_ratio: QQQ stop x MNQ price / QQQ price at the signal; native_atr: as is)
  stop_ticks         = stop_points / tick, rounded to the nearest tick (at least 1)
  target_ticks       = reward_risk x stop_ticks (exactly 3R in ticks of the rounded stop)
  risk_per_contract  = stop_ticks x tick_value + commission (round turn) + 2 x slippage ticks x tick_value
  contracts          = floor(budget / risk_per_contract), capped by the bot and firm maximums
  worst_case_loss    = contracts x (risk_per_contract + extra stop-slippage allowance)

A quantity is never rounded up. If one contract already exceeds the budget the trade is skipped and the
reason is recorded. Fractional contracts do not exist.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass
class SizingResult:
    contracts: int
    stop_points: float
    stop_ticks: int
    target_ticks: int
    risk_per_contract: float
    planned_loss: float          # contracts x risk_per_contract
    worst_case_loss: float       # planned_loss + gap allowance
    budget: float
    reason: str                  # "" if tradable

    def to_dict(self) -> dict:
        return asdict(self)


def size_trade(stop_points: float, budget: float, *, tick_size: float, tick_value: float,
               commission_rt: float, slip_ticks_per_side: float, extra_stop_slip_ticks: float,
               reward_risk: float, max_contracts: int, firm_max_contracts: int) -> SizingResult:
    if not (stop_points > 0) or math.isnan(stop_points):
        return SizingResult(0, stop_points, 0, 0, math.nan, 0.0, 0.0, budget, "invalid stop distance")
    stop_ticks = max(1, int(math.floor(stop_points / tick_size + 0.5)))
    target_ticks = int(round(reward_risk * stop_ticks))
    rpc = stop_ticks * tick_value + commission_rt + 2 * slip_ticks_per_side * tick_value
    n = int(math.floor(budget / rpc + 1e-9)) if rpc > 0 else 0
    cap = min(max_contracts, firm_max_contracts)
    n = min(n, cap)
    gap = extra_stop_slip_ticks * tick_value
    reason = ""
    if n < 1:
        reason = (f"one contract risks ${rpc:,.2f} (stop {stop_ticks} ticks + costs), more than the "
                  f"${budget:,.0f} budget: trade skipped")
        n = 0
    return SizingResult(n, stop_ticks * tick_size, stop_ticks, target_ticks, rpc, n * rpc, n * (rpc + gap),
                        budget, reason)


def convert_stop(stop_distance_signal: float, method: str, signal_price: float, exec_price: float) -> float:
    """Stop distance in execution-instrument points."""
    if method == "native_atr":
        return stop_distance_signal
    if method == "qqq_ratio":
        if not (signal_price > 0 and exec_price > 0):
            return math.nan
        return stop_distance_signal * exec_price / signal_price
    raise ValueError(f"unknown stop conversion {method}")
