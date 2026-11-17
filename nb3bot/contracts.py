"""Futures contract specifications and the quarterly roll schedule.

CME Micro E-mini Nasdaq-100 (MNQ): $2 x index, tick 0.25 = $0.50; E-mini (NQ): $20 x index, tick
0.25 = $5. Contract months H (Mar), M (Jun), U (Sep), Z (Dec); trading ends on the third Friday of the
contract month at 9:30 ET. The bot switches to the next contract `roll_days_before_expiry` calendar days
before expiry (default 8, the Thursday of the week before expiry, CME's usual equity-index roll date).
When the broker reports which contract is active, that answer wins and a mismatch is logged.
No smaller Nasdaq-100 futures contract than MNQ exists at CME; whether a firm offers any instrument
must be checked in its own contract list (ProjectX: /api/Contract/available).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

MONTH_CODES = {3: "H", 6: "M", 9: "U", 12: "Z"}


@dataclass(frozen=True)
class ContractSpec:
    root: str
    tick_size: float
    tick_value: float

    @property
    def point_value(self) -> float:
        return self.tick_value / self.tick_size


SPECS = {"MNQ": ContractSpec("MNQ", 0.25, 0.50), "NQ": ContractSpec("NQ", 0.25, 5.00)}


def third_friday(y: int, m: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(4 - d.weekday()) % 7)
    return d + timedelta(weeks=2)


def front_contract(today: date, roll_days_before_expiry: int = 8) -> tuple[int, int, date]:
    """(year, month, expiry) of the contract to trade on `today`."""
    y, m = today.year, today.month
    for _ in range(6):
        qm = ((m - 1) // 3 + 1) * 3
        exp = third_friday(y, qm)
        if today < exp - timedelta(days=roll_days_before_expiry):
            return y, qm, exp
        m = qm + 1
        if m > 12:
            m, y = 1, y + 1
    raise RuntimeError("no contract found")


def contract_code(root: str, y: int, m: int) -> str:
    """CME-style code, e.g. MNQZ26."""
    return f"{root}{MONTH_CODES[m]}{y % 100:02d}"


def projectx_contract_id(root: str, y: int, m: int) -> str:
    """ProjectX contract id convention seen in its documentation, e.g. CON.F.US.MNQ.Z26."""
    return f"CON.F.US.{root}.{MONTH_CODES[m]}{y % 100:02d}"


def in_roll_window(today: date, roll_days_before_expiry: int = 8, window_days: int = 1) -> bool:
    """True on the switch day itself and the day before (entries are paused around the roll)."""
    y, m, exp = front_contract(today - timedelta(days=window_days), roll_days_before_expiry)
    y2, m2, _ = front_contract(today + timedelta(days=window_days), roll_days_before_expiry)
    return (y, m) != (y2, m2)
