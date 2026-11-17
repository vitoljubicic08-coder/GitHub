"""Command line: python -m nb3bot <command> [options]. Run `python -m nb3bot -h` for the list."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import traceback
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXAMPLE = HERE / "config.example.toml"
REFERENCE = HERE / "validation" / "reference_nb3v2_qqq_trades.csv"
REPORTS = HERE / "validation" / "reports"


def _cfg(path):
    from nb3bot.config import load
    return load(path)


def _store_audit(cfg, echo=True):
    from nb3bot.storage import Audit, Store
    store = Store(Path(cfg.bot.state_dir) / "bot.sqlite")
    return store, Audit(cfg.bot.log_dir, store, echo=echo)


# ---------------------------------------------------------------------------- commands
def cmd_init(a):
    dst = Path(a.path)
    if dst.exists():
        sys.exit(f"{dst} already exists; not overwriting")
    shutil.copy(EXAMPLE, dst)
    print(f"wrote {dst}. Edit it, then run: python -m nb3bot check --config {dst}")


def cmd_verify(a):
    from nb3bot.replay.parity import run
    res = run(a.data, a.reference, a.out)
    print(f"parity {'PASSED' if res.passed else 'FAILED'}: {res.matched}/{res.reference_trades} trades identical, "
          f"{len(res.discrepancies)} discrepancies. Report: {Path(a.out) / 'parity_report.md'}")
    sys.exit(0 if res.passed else 1)


def cmd_replay(a):
    from nb3bot.performance import markdown, summarize
    from nb3bot.replay.data import load_sessions
    from nb3bot.replay.simlive import run_simulated
    cfg = _cfg(a.config)
    sessions = load_sessions(a.data, "QQQ")
    mnq = load_sessions(a.mnq_data, "MNQ") if a.mnq_data else None
    work = Path(a.workdir)
    if work.exists() and any(work.iterdir()):
        sys.exit(f"{work} is not empty; choose a new --workdir")
    res = run_simulated(cfg, sessions, a.start, a.end, work, mnq_sessions=mnq, echo=a.verbose,
                        parity_report=str(REPORTS / "parity_report.json"))
    s = summarize(res["trades"])
    (work / "performance.md").write_text(markdown(s))
    print(json.dumps(res["summary"], indent=1, default=str))
    print(markdown(s))


def _sources_and_broker(cfg, mode):
    """Build the market-data sources, the broker and a contract resolver for paper/practice/live."""
    from nb3bot.broker.base import ContractInfo
    from nb3bot.broker.paper import PaperBroker
    from nb3bot.broker.projectx import ProjectXBroker, ProjectXClient
    from nb3bot.clock import RealClock
    from nb3bot.data.providers import MassiveMinutes, ProjectXMinutes
    clock = RealClock()
    client = ProjectXClient.from_env(cfg.broker)
    px = ProjectXBroker(client, cfg.broker.account_id, cfg.broker.live_data)
    exe = ProjectXMinutes(client, "", cfg.broker.live_data)
    if cfg.strategy.signal_source == "QQQ":
        sig = MassiveMinutes("QQQ", cfg.data.qqq_api_base, cfg.data.qqq_api_key_env)
    else:
        sig = exe
    if mode == "paper":
        client.login()
        broker = PaperBroker(ContractInfo("", cfg.instrument.symbol, cfg.instrument.tick_size, cfg.instrument.tick_value, True),
                             cfg.account.starting_balance, cfg.costs.slippage_ticks_per_side,
                             cfg.costs.commission_round_turn / 2, clock)
    else:
        broker = px
    return clock, sig, exe, broker, px.contracts


def cmd_check(a):
    """Read-only checks: credentials, account, contracts, data. Never places or cancels an order."""
    from nb3bot.contracts import front_contract, projectx_contract_id
    from nb3bot.safety import authorization_status
    cfg = _cfg(a.config)
    ok = True
    print(f"mode {cfg.bot.mode}; broker {cfg.broker.name}")
    print("authorization:", authorization_status(cfg, cfg.bot.mode, REPORTS / "parity_report.json")[1])
    try:
        from nb3bot.broker.projectx import ProjectXBroker, ProjectXClient
        cl = ProjectXClient.from_env(cfg.broker)
        cl.login()
        accts = cl.accounts(True)
        print("ProjectX login OK; active accounts:", [(x["id"], x.get("name"), x.get("balance"), x.get("canTrade")) for x in accts])
        if cfg.broker.account_id and cfg.broker.account_id not in [x["id"] for x in accts]:
            ok = False
            print(f"  !! account_id {cfg.broker.account_id} is not among them")
        y, m, exp = front_contract(datetime.now().date(), cfg.instrument.roll_days_before_expiry)
        want = projectx_contract_id(cfg.instrument.symbol, y, m)
        cs = ProjectXBroker(cl, cfg.broker.account_id, cfg.broker.live_data).contracts(cfg.instrument.symbol)
        print(f"  calendar front contract {want} (expires {exp}); broker lists:",
              [(c.id, c.tick_size, c.tick_value, c.active) for c in cs])
        bars = cl.retrieve_bars(want, datetime.now().astimezone() - timedelta(hours=2), datetime.now().astimezone(),
                                2, 1, 200, cfg.broker.live_data, False)
        print(f"  MNQ minute bars in the last 2 h: {len(bars)}" + (f", latest {bars[0]['t'] if bars else ''}"))
    except Exception as e:  # noqa: BLE001
        ok = False
        print("ProjectX check failed:", e)
    if cfg.strategy.signal_source == "QQQ":
        try:
            from nb3bot.data.providers import MassiveMinutes
            src = MassiveMinutes("QQQ", cfg.data.qqq_api_base, cfg.data.qqq_api_key_env)
            now = datetime.now().astimezone()
            bars = src.fetch(now - timedelta(days=4), now)
            print(f"QQQ data OK: {len(bars)} minute bars in 4 days; real-time: {src.realtime}"
                  + (f"; latest {bars[-1].ts.isoformat()}" if bars else ""))
            if not src.realtime:
                ok = False
                print("  !! the provider reports DELAYED data: the bot will refuse to trade on it")
        except Exception as e:  # noqa: BLE001
            ok = False
            print("QQQ data check failed:", e)
    sys.exit(0 if ok else 1)


def cmd_run(a):
    from nb3bot.alerts import Alerter
    from nb3bot.app import Bot
    from nb3bot.dashboard.server import serve, token_for
    from nb3bot.timeutil import TradingCalendar, session_key
    cfg = _cfg(a.config)
    if a.mode != cfg.bot.mode:
        sys.exit(f"--mode {a.mode} does not match bot.mode = {cfg.bot.mode} in the config (both must agree)")
    if a.mode == "replay":
        sys.exit("use `python -m nb3bot replay` for historical replays")
    store, audit = _store_audit(cfg)
    alerter = Alerter(cfg.alerts, audit)
    clock, sig, exe, broker, resolver = _sources_and_broker(cfg, a.mode)
    bot = Bot(cfg, mode=a.mode, clock=clock, broker=broker, sig_source=sig, exec_source=exe, store=store, audit=audit,
              alerter=alerter, parity_report=str(REPORTS / "parity_report.json"))
    bot.contract_resolver = resolver
    warm = None
    if not store.get("engine_snapshot"):
        cal = TradingCalendar()
        d, keys = clock.now().date(), []
        while len(keys) < cfg.strategy.warmup_sessions:
            d = cal.previous_trading_day(d)
            keys.append(session_key(d))
        print(f"warming up the engine on {len(keys)} sessions of {sig.name} data (one-off)...")
        warm = [bot._download_session(sig, cfg.strategy.signal_source, k) for k in reversed(keys)]
    bot.startup(warmup_sessions=warm)
    if cfg.dashboard.enabled:
        serve(cfg.dashboard.host, cfg.dashboard.port, lambda: bot.status, lambda r: bot.kill.trigger(r),
              lambda: bot.set_armed(False, "dashboard"), token_for(cfg.bot.state_dir))
        print(f"dashboard: http://{cfg.dashboard.host}:{cfg.dashboard.port}")
    hb = Path(cfg.bot.state_dir) / "heartbeat"
    errors = 0
    try:
        while True:
            try:
                bot.step()
                errors = 0
            except Exception as e:  # noqa: BLE001 - never die silently with a position open
                errors += 1
                audit.log("loop_error", "CRITICAL", error=str(e), trace=traceback.format_exc()[-2000:])
                bot.mgr.halt(f"internal error: {e}")
                if errors >= 10:
                    bot.mgr.emergency_flatten("10 consecutive internal errors")
                    raise
                time.sleep(min(30, 2 ** errors))
            hb.write_text(clock.now().isoformat())
            clock.sleep(cfg.bot.loop_interval_seconds)
    except KeyboardInterrupt:
        if bot.mgr.active is not None and not a.leave_position:
            print("stopping: closing the open position and cancelling orders (use --leave-position to keep it)")
            bot.mgr.emergency_flatten("operator stopped the bot")
        audit.log("shutdown", reason="keyboard interrupt")


def cmd_flag(a):
    from nb3bot.safety import KillSwitch
    cfg = _cfg(a.config)
    store, audit = _store_audit(cfg, echo=False)
    if a.cmd == "arm":
        if KillSwitch(cfg.bot.state_dir).active():
            sys.exit("kill switch is active: run clear-kill first")
        store.put("armed", True)
        audit.log("armed", reason="operator command")
        print("armed: the bot will take valid entries when running (restart it if it is running)")
    elif a.cmd == "disarm":
        store.put("armed", False)
        audit.log("disarmed", reason="operator command")
        print("disarmed: no new entries")
    elif a.cmd == "kill":
        KillSwitch(cfg.bot.state_dir).trigger(a.reason)
        print("kill switch set: the running bot will cancel all orders, close positions and disarm within ~1 s")
    elif a.cmd == "clear-kill":
        KillSwitch(cfg.bot.state_dir).clear()
        store.put("halt_reasons", [])
        audit.log("kill_cleared", reason="operator command")
        print("kill switch and halts cleared; the bot stays DISARMED until you run arm")
    elif a.cmd == "clear-halts":
        store.put("halt_reasons", [])
        audit.log("halts_cleared", reason="operator command")
        print("halts cleared")


def cmd_status(a):
    cfg = _cfg(a.config)
    store, _ = _store_audit(cfg, echo=False)
    print(json.dumps({"armed": store.get("armed"), "halts": store.get("halt_reasons", []),
                      "active_trade": store.get("active_trade"), "account": (store.get("account") or {}).get("state"),
                      "engine_last_session": (store.get("engine_snapshot") or {}).get("last_session"),
                      "recent_events": store.recent_events(10)}, indent=1, default=str))


def cmd_authorize(a):
    from nb3bot.safety import PHRASE, write_authorization
    cfg = _cfg(a.config)
    expected = PHRASE.format(mode=a.mode.upper(), account=cfg.broker.account_id)
    print(f"This allows the bot to SEND {a.mode.upper()} ORDERS to ProjectX account {cfg.broker.account_id}.")
    print(f"Type exactly:  {expected}")
    typed = input("> ")
    p = write_authorization(cfg.bot.state_dir, a.mode, cfg.broker.account_id, typed)
    print(f"written {p}. Also set authorization.{a.mode}_orders_enabled = true in the config.")


def cmd_report(a):
    from nb3bot.performance import markdown, summarize
    cfg = _cfg(a.config)
    store, _ = _store_audit(cfg, echo=False)
    print(markdown(summarize(store.trades())))


def cmd_payout(a):
    from nb3bot.risk.account import AccountTracker
    cfg = _cfg(a.config)
    store, audit = _store_audit(cfg, echo=False)
    snap = store.get("account")
    if not snap:
        sys.exit("no account state yet")
    acc = AccountTracker.restore(snap)
    acc.payout(a.amount, a.floor_after)
    store.put("account", acc.snapshot())
    audit.log("payout_recorded", amount=a.amount, floor_after=a.floor_after, balance=acc.s.balance, floor=acc.s.floor)
    print(f"recorded payout ${a.amount:,.2f}; balance ${acc.s.balance:,.2f}, loss-limit floor ${acc.s.floor:,.2f}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m nb3bot", description="NB3 V2 automated futures bot")
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("init-config", help="write an example config file")
    s.add_argument("path", nargs="?", default="nb3bot.toml")
    s.set_defaults(fn=cmd_init)
    s = sp.add_parser("verify-parity", help="replay the engine against the verified 675 trades")
    s.add_argument("--data", required=True, help="QQQ 1-minute cache dir (market_*.npz) or CSV")
    s.add_argument("--reference", default=str(REFERENCE))
    s.add_argument("--out", default=str(REPORTS))
    s.set_defaults(fn=cmd_verify)
    s = sp.add_parser("replay", help="simulated-live replay of the whole bot over historical sessions")
    s.add_argument("--data", required=True)
    s.add_argument("--mnq-data", default="")
    s.add_argument("--config", default=None)
    s.add_argument("--start", type=int, required=True)
    s.add_argument("--end", type=int, required=True)
    s.add_argument("--workdir", required=True)
    s.add_argument("--verbose", action="store_true")
    s.set_defaults(fn=cmd_replay)
    s = sp.add_parser("check", help="read-only connection and data checks (no orders)")
    s.add_argument("--config", required=True)
    s.set_defaults(fn=cmd_check)
    s = sp.add_parser("run", help="run the bot (paper, practice or live)")
    s.add_argument("--config", required=True)
    s.add_argument("--mode", required=True, choices=["paper", "practice", "live"])
    s.add_argument("--leave-position", action="store_true", help="on Ctrl+C keep an open position (brackets stay)")
    s.set_defaults(fn=cmd_run)
    for name, hlp in (("arm", "allow new entries"), ("disarm", "stop new entries"), ("kill", "emergency stop"),
                      ("clear-kill", "clear the kill switch and halts"), ("clear-halts", "clear halts only")):
        s = sp.add_parser(name, help=hlp)
        s.add_argument("--config", required=True)
        if name == "kill":
            s.add_argument("--reason", default="operator kill command")
        s.set_defaults(fn=cmd_flag)
    s = sp.add_parser("status", help="print the saved state")
    s.add_argument("--config", required=True)
    s.set_defaults(fn=cmd_status)
    s = sp.add_parser("authorize", help="create the authorization file for practice or live orders")
    s.add_argument("--config", required=True)
    s.add_argument("--mode", required=True, choices=["practice", "live"])
    s.set_defaults(fn=cmd_authorize)
    s = sp.add_parser("report", help="performance report from the trade journal")
    s.add_argument("--config", required=True)
    s.set_defaults(fn=cmd_report)
    s = sp.add_parser("record-payout", help="record a withdrawal so the loss-limit tracking stays right")
    s.add_argument("--config", required=True)
    s.add_argument("--amount", type=float, required=True)
    s.add_argument("--floor-after", type=float, default=None, help="Topstep XFA: 0 (loss limit moves to a $0 balance)")
    s.set_defaults(fn=cmd_payout)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
