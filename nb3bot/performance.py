"""Performance tracking from the bot's own trade journal, compared with the research expectations."""
from __future__ import annotations

import math
from collections import defaultdict

from nb3bot.risk.guard import edge_status

BACKTEST = {"holdout_mean_r": 0.255, "holdout_win_rate": 0.48, "full_mean_r": 0.195, "r_sd": 1.42,
            "trades_per_day": 0.87}


def summarize(trades: list[dict], intents: list[dict] | None = None) -> dict:
    tr = sorted(trades, key=lambda t: t["session"])
    r = [t["r_multiple"] for t in tr if t.get("r_multiple") is not None and not math.isnan(t["r_multiple"])]
    pnl = [t["pnl"] for t in tr]
    eq, peak, mdd = 0.0, 0.0, 0.0
    for p in pnl:
        eq += p
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    months = defaultdict(list)
    for t in tr:
        months[t["session"] // 100].append(t["pnl"])
    reasons = defaultdict(int)
    for t in tr:
        reasons[t.get("exit_reason", "?")] += 1
    es, ed = edge_status(r)
    n = len(r)
    mean = sum(r) / n if n else math.nan
    se = BACKTEST["r_sd"] / math.sqrt(n) if n else math.nan
    return {"trades": len(tr), "win_rate": sum(x > 0 for x in pnl) / len(pnl) if pnl else math.nan,
            "mean_r": mean, "mean_r_95ci": (mean - 1.96 * se, mean + 1.96 * se) if n else None,
            "total_pnl": sum(pnl), "max_drawdown": mdd, "exit_reasons": dict(reasons),
            "by_month": {m: {"trades": len(v), "pnl": sum(v)} for m, v in sorted(months.items())},
            "edge_status": es, "edge_detail": ed, "backtest": BACKTEST}


def markdown(s: dict) -> str:
    lines = ["# NB3 V2 bot performance", "",
             f"* Trades: {s['trades']}", f"* Win rate: {s['win_rate']:.1%}" if s["trades"] else "* Win rate: —",
             f"* Mean R: {s['mean_r']:+.3f}" + (f" (95% range {s['mean_r_95ci'][0]:+.2f} to {s['mean_r_95ci'][1]:+.2f})" if s["mean_r_95ci"] else ""),
             f"* Total P&L: ${s['total_pnl']:,.2f}; worst drawdown ${s['max_drawdown']:,.2f}",
             f"* Exits: {s['exit_reasons']}",
             f"* Edge monitor: {s['edge_status']} — {s['edge_detail']}",
             f"* Research reference: holdout {BACKTEST['holdout_mean_r']:+.3f}R per trade, {BACKTEST['holdout_win_rate']:.0%} winners; "
             "fewer than ~100 trades cannot confirm or reject that", "", "| Month | Trades | P&L |", "|---|---|---|"]
    lines += [f"| {m} | {v['trades']} | ${v['pnl']:,.2f} |" for m, v in s["by_month"].items()]
    return "\n".join(lines) + "\n"
