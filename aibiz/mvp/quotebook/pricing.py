"""Price estimates from the business's own rules. Always a range, always labelled an estimate."""
from __future__ import annotations

import math
from dataclasses import dataclass

AREA_MIN, AREA_MAX = 10, 1000


class MissingInfo(ValueError):
    """The estimate needs a size or floor area the customer has not given yet."""

    def __init__(self, what: str):
        super().__init__(what)
        self.what = what


class InvalidInfo(ValueError):
    def __init__(self, what: str):
        super().__init__(what)
        self.what = what


@dataclass
class Estimate:
    low: float
    high: float
    minutes: int


def _round5(x: float, up: bool) -> float:
    return float(math.ceil(x / 5) * 5 if up else math.floor(x / 5) * 5)


def estimate(service, measure: str, size: str = "", area_m2: int = 0, slot_step: int = 30) -> Estimate:
    p, d = service.price, service.duration
    pct = float(p.get("range_pct", 10)) / 100
    if not service.needs_measure:
        base, minutes = float(p["fixed"]), int(d.get("minutes", 60))
    elif measure == "vehicle_size":
        if not size:
            raise MissingInfo("size")
        if size not in p["by_size"]:
            raise InvalidInfo("size")
        base = float(p["by_size"][size])
        minutes = int(d.get("by_size", {}).get(size, d.get("minutes", 60)))
    elif measure == "area_m2":
        if not area_m2:
            raise MissingInfo("area")
        if not AREA_MIN <= area_m2 <= AREA_MAX:
            raise InvalidInfo("area")
        base = max(float(p["per_m2"]) * area_m2, float(p.get("minimum", 0)))
        minutes = int(d.get("base_minutes", 60) + d.get("minutes_per_m2", 0) * area_m2)
        minutes = min(minutes, int(d.get("max_minutes", 600)))
    else:
        base, minutes = float(p.get("fixed", 0)), int(d.get("minutes", 60))
    minutes = int(math.ceil(minutes / slot_step) * slot_step)
    low = max(_round5(base * (1 - pct), up=False), 0.0)
    high = _round5(base * (1 + pct), up=True)
    return Estimate(low=low, high=high, minutes=minutes)
