"""Order-sending authorization, arming and the emergency kill switch.

Sending real orders needs ALL of the following, checked at start-up and before every entry:
  practice  config authorization.practice_orders_enabled = true, --mode practice, broker projectx,
            a practice authorization file for this account id, and a passing parity report.
  live      config authorization.live_orders_enabled = true, --mode live, broker projectx,
            a live authorization file for this account id (created by `python -m nb3bot authorize`
            after you type the confirmation sentence), and a passing parity report.
The shipped configuration has both switches OFF, so the bot cannot send orders until you change them.
Even when authorized, entries happen only while the bot is ARMED; the kill switch disarms it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PHRASE = "I AUTHORIZE {mode} ORDERS ON ACCOUNT {account}"


def auth_file(state_dir: str | Path, mode: str) -> Path:
    return Path(state_dir) / f"AUTHORIZE_{mode.upper()}.json"


def write_authorization(state_dir: str | Path, mode: str, account_id: int, typed: str) -> Path:
    expected = PHRASE.format(mode=mode.upper(), account=account_id)
    if typed.strip() != expected:
        raise ValueError(f"confirmation text did not match. Type exactly: {expected}")
    p = auth_file(state_dir, mode)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"mode": mode, "account_id": account_id, "phrase": expected,
                             "created": datetime.now(timezone.utc).isoformat()}, indent=1))
    return p


def parity_passed(report_path: str | Path) -> bool:
    try:
        return bool(json.loads(Path(report_path).read_text()).get("passed"))
    except (OSError, ValueError):
        return False


def authorization_status(cfg, mode: str, parity_report: str | Path) -> tuple[bool, str]:
    """(may_send_orders, explanation)."""
    if mode in ("replay", "paper"):
        return True, f"{mode} mode: simulated orders only, nothing is sent to any broker"
    if cfg.broker.name != "projectx":
        return False, "practice/live modes need broker.name = projectx"
    flag = cfg.authorization.practice_orders_enabled if mode == "practice" else cfg.authorization.live_orders_enabled
    if not flag:
        return False, f"authorization.{mode}_orders_enabled is false in the config"
    p = auth_file(cfg.bot.state_dir, mode)
    if not p.exists():
        return False, f"no {p.name}: run `python -m nb3bot authorize --mode {mode}` first"
    try:
        a = json.loads(p.read_text())
    except ValueError:
        return False, f"{p.name} is unreadable"
    if a.get("account_id") != cfg.broker.account_id or a.get("mode") != mode:
        return False, f"{p.name} is for account {a.get('account_id')}, config has {cfg.broker.account_id}"
    if not parity_passed(parity_report):
        return False, f"parity report {parity_report} missing or not passed: run `python -m nb3bot verify-parity`"
    return True, f"{mode} orders authorized for account {cfg.broker.account_id}"


class KillSwitch:
    def __init__(self, state_dir: str | Path):
        self.path = Path(state_dir) / "KILL"

    def trigger(self, reason: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"reason": reason, "ts": datetime.now(timezone.utc).isoformat()}))

    def active(self) -> bool:
        return self.path.exists()

    def reason(self) -> str:
        try:
            return json.loads(self.path.read_text()).get("reason", "kill switch")
        except (OSError, ValueError):
            return "kill switch"

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
