"""Business configuration (one JSON file per client) and environment settings.

The JSON holds everything that differs between businesses: services, price rules, opening
hours, resources (bays, teams), messaging and retention rules. Secrets never go in it: they come
from environment variables (see docs/CONFIG.md).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
MEASURES = ("vehicle_size", "area_m2", "none")


class ConfigError(ValueError):
    pass


def _hm(s: str) -> dt.time:
    m = HHMM.match(s)
    if not m:
        raise ConfigError(f"bad time {s!r} (expected HH:MM)")
    return dt.time(int(m.group(1)), int(m.group(2)))


@dataclass
class Service:
    id: str
    names: dict
    keywords: list
    price: dict
    duration: dict
    resources: list
    needs_measure: bool = True

    def name(self, lang: str) -> str:
        return self.names.get(lang) or next(iter(self.names.values()))


@dataclass
class Config:
    raw: dict
    path: str = ""
    business: dict = field(default_factory=dict)
    tz: ZoneInfo = None
    services: list = field(default_factory=list)
    resources: list = field(default_factory=list)
    hours: dict = field(default_factory=dict)          # day -> [(time, time)]
    closed_dates: set = field(default_factory=set)
    sizes: dict = field(default_factory=dict)
    measure: str = "none"

    # ------------------------------------------------------------------ accessors
    def section(self, name: str) -> dict:
        return self.raw.get(name, {})

    def get_service(self, sid: str):
        return next((s for s in self.services if s.id == sid), None)

    @property
    def booking(self) -> dict:
        b = {"slot_step_minutes": 30, "min_notice_hours": 12, "horizon_days": 30, "hold_minutes": 20,
             "buffer_minutes": 0, "require_owner_confirmation": True, "max_suggestions": 3}
        b.update(self.section("booking"))
        return b

    @property
    def messaging(self) -> dict:
        m = {"send_enabled": False, "channel": "dryrun", "reminder_hours_before": 24, "quiet_start": "21:00",
             "quiet_end": "08:00", "followup_after_hours": 48, "max_attempts": 6, "review_link": ""}
        m.update(self.section("messaging"))
        return m

    @property
    def retention(self) -> dict:
        r = {"conversation_days": 90, "customer_inactive_days": 730, "audit_days": 730}
        r.update(self.section("retention"))
        return r

    @property
    def rate_limits(self) -> dict:
        r = {"per_conversation_per_minute": 12, "per_ip_per_minute": 40, "login_per_ip_per_minute": 5}
        r.update(self.section("rate_limits"))
        return r

    @property
    def assistant(self) -> dict:
        a = {"interpreter": "rules", "llm_model": "claude-opus-5-5", "llm_timeout_s": 10.0,
             "default_language": self.business.get("default_language", "hr"), "max_unclear": 2}
        a.update(self.section("assistant"))
        return a


def validate(raw: dict) -> list:
    """Return a list of human-readable problems (empty if the file is valid)."""
    errs = []
    b = raw.get("business", {})
    for k in ("id", "name", "timezone"):
        if not b.get(k):
            errs.append(f"business.{k} is required")
    try:
        ZoneInfo(b.get("timezone", "Europe/Zagreb"))
    except Exception:
        errs.append(f"unknown time zone {b.get('timezone')!r}")
    if raw.get("measure", "none") not in MEASURES:
        errs.append(f"measure must be one of {MEASURES}")
    res_ids = [r.get("id") for r in raw.get("resources", [])]
    if not res_ids:
        errs.append("at least one resource (bay, team) is required")
    if len(set(res_ids)) != len(res_ids):
        errs.append("resource ids must be unique")
    hours = raw.get("hours", {})
    for d in hours:
        if d not in DAYS:
            errs.append(f"hours: unknown day {d!r}")
            continue
        for iv in hours[d]:
            try:
                a, z = _hm(iv[0]), _hm(iv[1])
                if a >= z:
                    errs.append(f"hours.{d}: opening {iv[0]} must be before closing {iv[1]}")
            except (ConfigError, IndexError, TypeError) as e:
                errs.append(f"hours.{d}: {e}")
    for s in raw.get("closed_dates", []):
        try:
            dt.date.fromisoformat(s)
        except ValueError:
            errs.append(f"closed_dates: bad date {s!r}")
    sids = set()
    measure = raw.get("measure", "none")
    for s in raw.get("services", []):
        sid = s.get("id")
        if not sid or sid in sids:
            errs.append(f"service id missing or duplicated: {sid!r}")
        sids.add(sid)
        p = s.get("price", {})
        if measure == "vehicle_size" and s.get("needs_measure", True):
            missing = set(raw.get("sizes", {})) - set(p.get("by_size", {}))
            if missing:
                errs.append(f"service {sid}: price.by_size missing sizes {sorted(missing)}")
        elif measure == "area_m2" and s.get("needs_measure", True):
            if not p.get("per_m2"):
                errs.append(f"service {sid}: price.per_m2 is required")
        elif "fixed" not in p and not s.get("needs_measure", True):
            errs.append(f"service {sid}: price.fixed is required when the service needs no measure")
        for r in s.get("resources", res_ids):
            if r not in res_ids:
                errs.append(f"service {sid}: unknown resource {r!r}")
        if not s.get("names"):
            errs.append(f"service {sid}: names is required")
    if not sids:
        errs.append("at least one service is required")
    m = raw.get("messaging", {})
    if m.get("send_enabled"):
        errs.append("messaging.send_enabled is true, but this MVP ships no live sender; keep it false")
    return errs


def load_config(path) -> Config:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    errs = validate(raw)
    if errs:
        raise ConfigError(f"{path}: " + "; ".join(errs))
    cfg = Config(raw=raw, path=str(path))
    cfg.business = raw["business"]
    cfg.tz = ZoneInfo(cfg.business["timezone"])
    cfg.measure = raw.get("measure", "none")
    cfg.sizes = raw.get("sizes", {})
    cfg.resources = raw["resources"]
    all_res = [r["id"] for r in cfg.resources]
    for s in raw["services"]:
        cfg.services.append(Service(id=s["id"], names=s["names"], keywords=[k.lower() for k in s.get("keywords", [])],
                                    price=s.get("price", {}), duration=s.get("duration", {"minutes": 60}),
                                    resources=s.get("resources", all_res), needs_measure=s.get("needs_measure", True)))
    cfg.hours = {d: [(_hm(a), _hm(z)) for a, z in raw.get("hours", {}).get(d, [])] for d in DAYS}
    cfg.closed_dates = {dt.date.fromisoformat(s) for s in raw.get("closed_dates", [])}
    return cfg


@dataclass
class Env:
    """Settings that must not live in the business JSON."""
    admin_token: str = ""
    secret_key: str = ""
    allow_live_send: bool = False
    anthropic_enabled: bool = False

    @classmethod
    def from_environ(cls, environ=None) -> "Env":
        e = os.environ if environ is None else environ
        return cls(admin_token=e.get("QB_ADMIN_TOKEN", ""), secret_key=e.get("QB_SECRET_KEY", ""),
                   allow_live_send=e.get("QB_ALLOW_LIVE_SEND", "") == "1",
                   anthropic_enabled=e.get("QB_ENABLE_LLM", "") == "1")
