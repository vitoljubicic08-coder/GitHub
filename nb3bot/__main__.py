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
    src = EXAMPLE if not a.profile else HERE / "profiles" / f"{a.profile}.toml"
    if not src.exists():
        sys.exit(f"unknown profile {a.profile}; available: {', '.join(p.stem for p in (HERE / 'profiles').glob('*.toml'))}")
    shutil.copy(src, dst)
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
    """Market-data sources, broker, contract resolver and (with simulated prices) the fixed contract.
    ProjectX credentials are only needed when ProjectX supplies data or receives orders."""
    from nb3bot.broker.base import ContractInfo
    from nb3bot.broker.paper import PaperBroker
    from nb3bot.broker.projectx import ProjectXBroker, ProjectXClient
    from nb3bot.clock import RealClock
    from nb3bot.data.providers import AlpacaMinutes, MassiveMinutes, ProjectXMinutes, SyntheticFutures
    from nb3bot.risk.account import rules_from_config
    clock = RealClock()
    cache = {}

    def px():
        if "c" not in cache:
            cache["c"] = ProjectXClient.from_env(cfg.broker)
        return cache["c"]

    sig = None
    if cfg.strategy.signal_source == "QQQ":
        if cfg.data.qqq_provider == "alpaca":
            sig = AlpacaMinutes("QQQ", cfg.data.alpaca_api_base, cfg.data.alpaca_key_id_env, cfg.data.alpaca_secret_env,
                                cfg.data.alpaca_live_feed, cfg.data.alpaca_history_feed)
        elif cfg.data.qqq_provider == "massive":
            sig = MassiveMinutes("QQQ", cfg.data.qqq_api_base, cfg.data.qqq_api_key_env)
        else:
            sys.exit("data.qqq_provider = replay is only for `python -m nb3bot replay`")
    fixed = None
    if cfg.data.mnq_provider == "synthetic":
        exe = SyntheticFutures(sig, cfg.data.synthetic_ratio, cfg.instrument.tick_size, cfg.instrument.symbol)
        fixed = ContractInfo("SIM.MNQ", f"{cfg.instrument.symbol} (SIMULATED: QQQ x {cfg.data.synthetic_ratio:g})",
                             cfg.instrument.tick_size, cfg.instrument.tick_value, True)
    else:
        exe = ProjectXMinutes(px(), "", cfg.broker.live_data)
    if sig is None:
        sig = exe
    if mode == "paper":
        start_balance = rules_from_config(cfg.account).starting_balance
        broker = PaperBroker(fixed or ContractInfo("", cfg.instrument.symbol, cfg.instrument.tick_size, cfg.instrument.tick_value, True),
                             start_balance, cfg.costs.slippage_ticks_per_side, cfg.costs.commission_round_turn / 2, clock)
        resolver = None
        if fixed is None:
            px().login()
            resolver = ProjectXBroker(px(), cfg.broker.account_id, cfg.broker.live_data).contracts
    else:
        broker = ProjectXBroker(px(), cfg.broker.account_id, cfg.broker.live_data)
        resolver = broker.contracts
    return clock, sig, exe, broker, resolver, fixed


def _warmup(bot, cfg, sig, clock):
    """Download the history the noise band and ATR need (once). Retries each session up to 3 times."""
    from nb3bot.timeutil import TradingCalendar, session_key
    cal = TradingCalendar()
    d, keys = clock.now().date(), []
    while len(keys) < cfg.strategy.warmup_sessions:
        d = cal.previous_trading_day(d)
        keys.append(session_key(d))
    keys.reverse()
    print(f"one-off warm-up: downloading {len(keys)} sessions of QQQ minute data from {sig.name} ...", flush=True)
    out = []
    for i, k in enumerate(keys, 1):
        for attempt in range(3):
            try:
                out.append(bot._download_session(sig, cfg.strategy.signal_source, k))
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    sys.exit(f"warm-up failed on {k}: {e}")
                time.sleep(2 * (attempt + 1))
        if i % 25 == 0 or i == len(keys):
            print(f"  {i}/{len(keys)} sessions", flush=True)
    return out


def cmd_check(a):
    """Read-only checks: credentials, account, contracts, data. Never places or cancels an order."""
    from nb3bot.contracts import front_contract, projectx_contract_id
    from nb3bot.safety import authorization_status
    cfg = _cfg(a.config)
    ok = True
    print(f"profile {cfg.bot.profile or '-'}; mode {cfg.bot.mode}; broker {cfg.broker.name}")
    print("authorization:", authorization_status(cfg, cfg.bot.mode, REPORTS / "parity_report.json")[1])
    needs_px = cfg.broker.name == "projectx" or cfg.data.mnq_provider == "projectx" or cfg.strategy.signal_source == "MNQ"
    if needs_px:
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
    else:
        print(f"ProjectX not needed: {cfg.instrument.symbol} prices are "
              + (f"SIMULATED as QQQ x {cfg.data.synthetic_ratio:g}" if cfg.data.mnq_provider == "synthetic" else cfg.data.mnq_provider))
    if cfg.strategy.signal_source == "QQQ":
        try:
            now = datetime.now().astimezone()
            if cfg.data.qqq_provider == "alpaca":
                from nb3bot.data.providers import AlpacaMinutes
                src = AlpacaMinutes("QQQ", cfg.data.alpaca_api_base, cfg.data.alpaca_key_id_env, cfg.data.alpaca_secret_env,
                                    cfg.data.alpaca_live_feed, cfg.data.alpaca_history_feed)
                hist = src.fetch(now - timedelta(days=5), now - timedelta(minutes=20))
                live = src.fetch(now - timedelta(hours=3), now)
                print(f"Alpaca OK: history feed {src.history_feed}: {len(hist)} QQQ minute bars in the last 5 days"
                      + (f" (latest {hist[-1].ts:%Y-%m-%d %H:%M} UTC)" if hist else ""))
                print(f"  live feed {cfg.data.alpaca_live_feed}: {len(live)} bars in the last 3 hours"
                      + (f" (latest {live[-1].ts:%Y-%m-%d %H:%M} UTC)" if live else " (normal outside US market hours)"))
                for n in src.notes:
                    print("  note:", n)
            else:
                from nb3bot.data.providers import MassiveMinutes
                src = MassiveMinutes("QQQ", cfg.data.qqq_api_base, cfg.data.qqq_api_key_env)
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


def safety_report(cfg) -> tuple[bool, list[str]]:
    """(cannot_send_real_orders, lines). Used by `safety-check` and by the macOS launcher."""
    from nb3bot.risk.account import rules_from_config
    r = rules_from_config(cfg.account)
    lines = [f"profile:            {cfg.bot.profile or '-'}",
             f"mode:               {cfg.bot.mode}",
             f"broker:             {cfg.broker.name}" + (" (simulated fills inside this program)" if cfg.broker.name == "paper" else ""),
             f"signal data:        {cfg.strategy.signal_source} via {cfg.data.qqq_provider if cfg.strategy.signal_source == 'QQQ' else cfg.data.mnq_provider}",
             f"{cfg.instrument.symbol} prices:         "
             + (f"SIMULATED (QQQ x {cfg.data.synthetic_ratio:g})" if cfg.data.mnq_provider == "synthetic" else cfg.data.mnq_provider),
             f"account rules:      {r.name}: start ${r.starting_balance:,.0f}, max loss ${r.max_loss:,.0f} ({r.trailing} trailing), "
             f"target {('$%s' % format(r.profit_target, ',.0f')) if r.profit_target else 'none'}, daily limit "
             f"{('$%s' % format(r.daily_loss_limit, ',.0f')) if r.daily_loss_limit else 'none'}",
             f"risk per trade:     evaluation ${cfg.risk.evaluation_risk_per_trade:,.0f}, funded ${cfg.risk.funded_risk_per_trade:,.0f} "
             f"(phase: {cfg.risk.phase}); max {cfg.risk.max_contracts} contract(s)",
             f"strategy:           target {cfg.strategy.reward_risk:g}R, up to {cfg.strategy.max_trades_per_day} trade(s) a day",
             f"daily limits:       loss -${min(cfg.risk.max_daily_loss, r.daily_loss_limit or 1e18):,.0f}"
             f" ({'open trade closed and day locked' if cfg.risk.flatten_on_daily_loss else 'entries only'}), profit cap "
             + (f"${cfg.risk.max_daily_profit:,.0f}" if cfg.risk.max_daily_profit > 0 else "off")
             + (f", best-day cap ${r.consistency * r.profit_target:,.0f} (evaluation)"
                if cfg.risk.consistency_day_cap and r.consistency and r.profit_target else ""),
             f"practice orders:    {'ENABLED' if cfg.authorization.practice_orders_enabled else 'disabled'}",
             f"live orders:        {'ENABLED' if cfg.authorization.live_orders_enabled else 'disabled'}"]
    safe = (cfg.broker.name == "paper" and cfg.bot.mode in ("paper", "replay")
            and not cfg.authorization.practice_orders_enabled and not cfg.authorization.live_orders_enabled)
    return safe, lines


def cmd_safety(a):
    cfg = _cfg(a.config)
    safe, lines = safety_report(cfg)
    print("\n".join(lines))
    print("RESULT: SIMULATION ONLY - this configuration cannot send any order to a broker" if safe
          else "RESULT: this configuration CAN send orders to a broker account")
    sys.exit(0 if safe else 1)


def cmd_demo(a):
    """Offline demo on SYNTHETIC prices: the whole bot + dashboard, no accounts or internet needed."""
    import tempfile
    import webbrowser
    from nb3bot.config import Config, load
    from nb3bot.dashboard.server import serve
    from nb3bot.replay.simlive import build, run_day
    from nb3bot.replay.synthetic import synthetic_sessions
    cfg = load(a.config) if a.config else Config()
    cfg = replace(cfg, bot=replace(cfg.bot, profile=(cfg.bot.profile or "demo") + " / OFFLINE DEMO",
                                   banner="OFFLINE DEMO on SYNTHETIC prices (random data, not the market): checks the "
                                          "installation and shows how the bot behaves. Nothing is sent anywhere."),
                  data=replace(cfg.data, allow_empty_minutes=False, eod_rebuild_delay_minutes=3))
    sessions = synthetic_sessions(a.days + 20, seed=a.seed)
    work = Path(tempfile.mkdtemp(prefix="nb3bot_demo_"))
    rig = build(cfg, sessions, sessions[20].key, work)
    port = cfg.dashboard.port if a.port is None else a.port
    srv = serve(cfg.dashboard.host, port, lambda: rig.bot.status, lambda r: rig.bot.kill.trigger(r),
                lambda: rig.bot.set_armed(False, "dashboard"), "demo")
    url = f"http://{cfg.dashboard.host}:{srv.server_address[1]}"
    print(f"OFFLINE DEMO (synthetic prices). Dashboard: {url}  (dashboard token for the buttons: demo)", flush=True)
    if a.open:
        webbrowser.open(url)
    for s in sessions[20:]:
        print(f"  simulating session {s.key} ...", flush=True)
        run_day(rig, s.key, hook=(lambda r: time.sleep(a.pace)) if a.pace > 0 else None)
        rig.bot._last_status = -1e9
        rig.bot._publish_status(rig.clock.now())
    tr = rig.store.trades()
    print(f"demo finished: {len(tr)} simulated trades, P&L ${sum(t['pnl'] for t in tr):+,.2f} on synthetic prices "
          f"(meaningless as a result; it only shows the machinery). Files: {work}", flush=True)
    if a.wait:
        print("dashboard stays open; press Ctrl+C to quit.", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    srv.shutdown()


def cmd_run(a):
    from nb3bot.alerts import Alerter
    from nb3bot.app import Bot
    from nb3bot.dashboard.server import serve, token_for
    cfg = _cfg(a.config)
    if a.mode != cfg.bot.mode:
        sys.exit(f"--mode {a.mode} does not match bot.mode = {cfg.bot.mode} in the config (both must agree)")
    if a.mode == "replay":
        sys.exit("use `python -m nb3bot replay` for historical replays")
    store, audit = _store_audit(cfg)
    alerter = Alerter(cfg.alerts, audit)
    clock, sig, exe, broker, resolver, fixed = _sources_and_broker(cfg, a.mode)
    bot = Bot(cfg, mode=a.mode, clock=clock, broker=broker, sig_source=sig, exec_source=exe, store=store, audit=audit,
              alerter=alerter, parity_report=str(REPORTS / "parity_report.json"), contract=fixed)
    bot.contract_resolver = resolver
    warm = None if store.get("engine_snapshot") else _warmup(bot, cfg, sig, clock)
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
    s = sp.add_parser("init-config", help="write an example config file (or a ready-made profile)")
    s.add_argument("path", nargs="?", default="nb3bot.toml")
    s.add_argument("--profile", default="", help="e.g. tradingview_50k_demo")
    s.set_defaults(fn=cmd_init)
    s = sp.add_parser("safety-check", help="show what the config can do; exit 0 only if it cannot send orders")
    s.add_argument("--config", required=True)
    s.set_defaults(fn=cmd_safety)
    s = sp.add_parser("demo", help="offline demo on synthetic prices with the dashboard (no accounts needed)")
    s.add_argument("--config", default=None)
    s.add_argument("--days", type=int, default=5)
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--pace", type=float, default=0.002, help="real seconds per simulated 5-second step")
    s.add_argument("--open", action="store_true", help="open the dashboard in the browser")
    s.add_argument("--wait", action="store_true", help="keep the dashboard open after the demo")
    s.add_argument("--port", type=int, default=None, help="dashboard port (default: from the config, 8765)")
    s.set_defaults(fn=cmd_demo)
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
