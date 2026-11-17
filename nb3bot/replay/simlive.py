"""Simulated-live replay: the COMPLETE live stack (data feeds, engine, risk guard, execution manager,
paper broker, persistence, alerts) driven by a simulated clock over historical sessions.

This is how the bot is rehearsed without a market: every component runs exactly as it does live,
only the clock and the data source are simulated. By default MNQ prices are synthesised as
QQQ x 41.3 (the measured NQ/QQQ ratio); pass real MNQ minute data with `mnq_sessions` when available.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, time
from pathlib import Path

from nb3bot.alerts import Alerter
from nb3bot.app import Bot, key_date
from nb3bot.broker.base import ContractInfo
from nb3bot.broker.paper import PaperBroker
from nb3bot.clock import SimClock
from nb3bot.data.providers import ReplayMinutes
from nb3bot.replay.data import Session
from nb3bot.storage import Audit, Store
from nb3bot.timeutil import NY

SYNTHETIC_RATIO = 41.3


@dataclass
class SimRig:
    bot: Bot
    clock: SimClock
    broker: PaperBroker
    store: Store
    sig_src: ReplayMinutes
    exe_src: ReplayMinutes
    alerts: list


def build(cfg, sessions: list[Session], start_key: int, workdir: str | Path, mnq_sessions: list[Session] | None = None,
          ratio: float = SYNTHETIC_RATIO, echo: bool = False, parity_report: str = "", warm: bool = True) -> SimRig:
    work = Path(workdir)
    cfg = replace(cfg, bot=replace(cfg.bot, mode="replay", state_dir=str(work / "state"), log_dir=str(work / "logs")))
    first = next(s for s in sessions if s.key >= start_key)
    clock = SimClock(datetime.combine(key_date(first.key), time(9, 0), NY))
    store = Store(work / "state" / "bot.sqlite")
    audit = Audit(work / "logs", store, echo=echo)
    alerts: list = []
    alerter = Alerter(cfg.alerts, audit, sender=lambda lvl, txt: alerts.append((lvl, txt)))
    sig_src = ReplayMinutes("replay:QQQ", sessions, clock)
    exe_src = ReplayMinutes("replay:MNQ", mnq_sessions or sessions, clock, scale=1.0 if mnq_sessions else ratio,
                            tick=cfg.instrument.tick_size)
    c = ContractInfo("SIM.MNQ", "MNQ (synthetic QQQ x ratio)" if not mnq_sessions else "MNQ (replay)",
                     cfg.instrument.tick_size, cfg.instrument.tick_value, True)
    broker = PaperBroker(c, 0.0, slip_ticks=cfg.costs.slippage_ticks_per_side,
                         commission_per_side=cfg.costs.commission_round_turn / 2, clock=clock)
    bot = Bot(cfg, mode="replay", clock=clock, broker=broker, sig_source=sig_src, exec_source=exe_src, store=store,
              audit=audit, alerter=alerter, parity_report=parity_report, contract=c)
    broker.balance = bot.account.s.balance
    bot.startup(warmup_sessions=[s for s in sessions if s.key < start_key] if warm else None)
    return SimRig(bot, clock, broker, store, sig_src, exe_src, alerts)


def run_day(rig: SimRig, key: int, step_seconds: float = 5.0, hook=None, until: time = time(16, 10)) -> None:
    d = key_date(key)
    rig.clock.set(datetime.combine(d, time(9, 20), NY))
    stop = datetime.combine(d, until, NY)
    while rig.clock.now() < stop:
        rig.bot.step()
        if hook is not None:
            hook(rig)
        rig.clock.sleep(step_seconds)


def run_simulated(cfg, sessions: list[Session], start_key: int, end_key: int, workdir: str | Path,
                  mnq_sessions: list[Session] | None = None, ratio: float = SYNTHETIC_RATIO,
                  step_seconds: float = 5.0, echo: bool = False, parity_report: str = "") -> dict:
    rig = build(cfg, sessions, start_key, workdir, mnq_sessions, ratio, echo, parity_report)
    for s in sessions:
        if start_key <= s.key <= end_key:
            run_day(rig, s.key, step_seconds)
    trades = rig.store.trades()
    summary = {"sessions": sum(1 for s in sessions if start_key <= s.key <= end_key), "trades": len(trades),
               "total_pnl": sum(t["pnl"] for t in trades), "final_balance": rig.bot.account.s.balance,
               "halts": rig.bot.mgr.halt_reasons}
    Path(workdir, "simulated_summary.json").write_text(json.dumps({"summary": summary, "trades": trades}, indent=1, default=str))
    rig.store.db.close()
    return {"summary": summary, "trades": trades, "bot": rig.bot}
