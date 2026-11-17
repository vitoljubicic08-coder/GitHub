"""Automated parity check: bot engine replay vs the verified 675-trade NB3 V2 backtest.

Compares, trade by trade: session date, signal bar (timestamp), direction, entry minute, entry fill,
stop distance, stop and target prices, exit minute, exit price, exit reason, net and gross R.
Any difference is reported as a discrepancy; the check passes only with zero unexplained ones.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

from nb3bot.replay.data import load_sessions
from nb3bot.replay.runner import ReplayTrade, replay_backtest
from nb3bot.timeutil import minute_start

FIELDS_FLOAT = ("fill", "dist", "exit_px", "r_net", "r_gross")
FIELDS_EXACT = ("direction", "signal_bar", "entry_min", "exit_min", "reason")
TOL = 1e-9


@dataclass
class ParityResult:
    reference_trades: int
    bot_trades: int
    matched: int
    discrepancies: list[dict]
    max_abs_diff: dict

    @property
    def passed(self) -> bool:
        return not self.discrepancies and self.reference_trades == self.bot_trades == self.matched


def read_reference(path: str | Path) -> dict[int, dict]:
    out = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            out[int(row["dkey"])] = row
    return out


def compare(reference: dict[int, dict], trades: list[ReplayTrade]) -> ParityResult:
    bot = {t.dkey: t for t in trades}
    disc, maxd, matched = [], {f: 0.0 for f in FIELDS_FLOAT}, 0
    for k in sorted(set(reference) | set(bot)):
        ref, t = reference.get(k), bot.get(k)
        if ref is None or t is None:
            disc.append({"dkey": k, "issue": "missing in bot" if t is None else "extra trade in bot"})
            continue
        bad = []
        for f in FIELDS_EXACT:
            rv = ref[f] if f == "reason" else int(ref[f])
            if getattr(t, f) != rv:
                bad.append(f"{f}: reference {rv} vs bot {getattr(t, f)}")
        for f in FIELDS_FLOAT:
            d = abs(float(ref[f]) - getattr(t, f))
            maxd[f] = max(maxd[f], d)
            if not d <= TOL:
                bad.append(f"{f}: reference {ref[f]} vs bot {getattr(t, f)!r}")
        if bad:
            disc.append({"dkey": k, "issue": "; ".join(bad)})
        else:
            matched += 1
    return ParityResult(len(reference), len(bot), matched, disc, maxd)


def write_report(res: ParityResult, trades: list[ReplayTrade], out_dir: str | Path, data_source: str) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    r = [t.r_net for t in trades]
    summary = {
        "passed": res.passed, "reference_trades": res.reference_trades, "bot_trades": res.bot_trades,
        "matched_exactly": res.matched, "discrepancies": len(res.discrepancies), "tolerance": TOL,
        "max_abs_diff": res.max_abs_diff, "data_source": data_source,
        "bot_stats": {"trades": len(r), "mean_r": sum(r) / len(r) if r else math.nan,
                      "win_rate": sum(x > 0 for x in r) / len(r) if r else math.nan, "total_r": sum(r)},
    }
    (out / "parity_report.json").write_text(json.dumps({**summary, "discrepancy_list": res.discrepancies}, indent=1))
    lines = ["# NB3 V2 bot engine vs verified backtest — parity report", "",
             f"* Result: **{'PASS' if res.passed else 'FAIL'}**",
             f"* Reference trades: {res.reference_trades}; bot trades: {res.bot_trades}; "
             f"identical: {res.matched}; discrepancies: {len(res.discrepancies)}",
             f"* Fields compared per trade: session, signal bar and time, direction, entry minute, entry fill, "
             f"stop distance, stop and target, exit minute, exit price, exit reason, net R, gross R "
             f"(prices and R to within {TOL:g})",
             "* Largest absolute differences: " + ", ".join(f"{k} {v:.2e}" for k, v in res.max_abs_diff.items()),
             f"* Bot replay: {len(r)} trades, mean {summary['bot_stats']['mean_r']:+.4f}R, "
             f"win rate {summary['bot_stats']['win_rate']:.1%}, total {summary['bot_stats']['total_r']:+.1f}R",
             f"* Data: {data_source}", ""]
    if res.discrepancies:
        lines += ["## Discrepancies (each one is a bug until explained)", "", "| Session | Issue |", "|---|---|"]
        lines += [f"| {d['dkey']} | {d['issue']} |" for d in res.discrepancies]
    lines += ["", "## First 10 trades (New York signal time)", "",
              "| Session | Signal bar opens | Side | Entry | Stop | Target | Exit | Reason | R |", "|---|---|---|---|---|---|---|---|---|"]
    for t in trades[:10]:
        ts = minute_start(t.dkey, t.signal_bar * 5).astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))
        lines.append(f"| {t.dkey} | {ts:%H:%M} | {'BUY' if t.direction > 0 else 'SELL'} | {t.fill:.4f} | {t.stop:.4f} | "
                     f"{t.target:.4f} | {t.exit_px:.4f} | {t.reason} | {t.r_net:+.3f} |")
    p = out / "parity_report.md"
    p.write_text("\n".join(lines) + "\n")
    return p


def run(data: str, reference: str, out_dir: str, end_key: int = 20260331) -> ParityResult:
    sessions = load_sessions(data, "QQQ")
    trades, _ = replay_backtest(sessions, end_key=end_key)
    res = compare(read_reference(reference), trades)
    write_report(res, trades, out_dir, f"{data} ({len(sessions)} sessions, up to {end_key})")
    return res
