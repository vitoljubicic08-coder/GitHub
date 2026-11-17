#!/usr/bin/env python3
"""10-year backtest of the Lucid "steady" setting (NB3 signal, 0.3 ATR stop, 1.5R, up to 2 trades a day),
QQQ 1-minute data 2016-01 .. 2026-03 executed as MNQ, three ways:

  1. trades: per-year R statistics (1 MNQ tick of slippage per market/stop fill, $1.50 per round turn);
  2. plain account: $350 risk budget per trade, whole MNQ = floor($350 / risk per MNQ incl. costs),
     at most 3, no prop-firm rules;
  3. LucidFlex accounts in date order (no resampling): a $130 account is bought, traded with the bot's
     rules, and replaced the next day when it fails. Rules as in the bot's lucid_flex_50k_steady profile:
       - entry skipped if one MNQ risks more than $350, if today's P&L minus the worst case would pass
         -$800, or (evaluation) if today's P&L plus the full target would pass $1,200 (40% x $3,000);
       - if the worst case would leave less than $100 above the loss limit the bot halts: the account is
         treated as given up (it cannot trade without risking the limit) and a new one is bought
         (`--trade-to-limit`: keep trading until the limit is actually hit instead);
       - $2,000 limit trailing the end-of-day high, breached by the worst open P&L, locked at +$100;
         $3,000 target with best day <= 40%; funded scaling plan 20/30/40 micros;
       - payout when 5 days >= $150 and positive cycle profit: min(50% of profit, $2,000, profit - $600),
         at least $500; 90% split, $30 per transfer; after 5 payouts the account moves to live (ends).
Dollar risk uses each day's own volatility (a true backtest). `--today-vol` rescales it to Sep-Nov 2026.

  python3 backtest/backtest_10y_steady.py --inst <10-year cache> [--today-vol]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import intraday_lab as il  # noqa: E402
import lab4  # noqa: E402
import lab6  # noqa: E402
import lucid5 as lc  # noqa: E402
import prop_sim as ps  # noqa: E402

TICK_USD, COMM, SLIP_TICKS, GAP_USD = 0.50, 1.50, 1.0, 2.0
BUDGET, MAX_C, DAILY_LOSS, RESERVE = 350.0, 3, 800.0, 100.0
START, MLL, LOCK, TARGET, CONS = 50000.0, 2000.0, 100.0, 3000.0, 0.40
FEE, WIN_DAY, WIN_DAYS, PAY_CAP, PAY_MIN, KEEP, SPLIT, XFER, MAX_PAY = 130.0, 150.0, 5, 2000.0, 500.0, 500.0, 0.9, 30.0, 5
RR = 1.5


def build(d, today_vol=False):
    sig = lab6.nb3_signals(d, 2)
    t = lab6.bracket6(d, sig, RR, 0.3, max_trades=2, slip=ps.MNQ_TICK_Q, commission=0.0, tick=ps.MNQ_TICK_Q)
    pool = lc.pool_from_trades(d, t)
    if today_vol:
        ref = lc.build_pool(d, 0, 99999999, 0.3, 3.0, 1)
        scale = 275.3 / float(np.median(ref["dpr1"][ref["has1"]][-250:]))
        for j in (1, 2):
            pool[f"dpr{j}"] *= scale
    return t, pool


def contracts(dpr, cap):
    rpc = dpr + COMM + 2 * SLIP_TICKS * TICK_USD
    return min(int(math.floor(BUDGET / rpc + 1e-9)), MAX_C, cap), rpc


def plain_account(pool):
    pnl = np.zeros(pool["n"])
    for i in range(pool["n"]):
        for j in (1, 2):
            if pool[f"has{j}"][i]:
                c, _ = contracts(pool[f"dpr{j}"][i], 40)
                pnl[i] += c * (pool[f"r{j}"][i] * pool[f"dpr{j}"][i] - COMM)
    return pnl


def lucid_replay(pool, dkey, give_up: bool = True):
    accts, cur = [], None

    def new(i):
        return {"start": int(dkey[i]), "phase": "eval", "P": 0.0, "peak": 0.0, "floor": -MLL, "fixed": False,
                "best": 0.0, "win": 0, "cyc": 0.0, "pays": [], "end": None, "outcome": "open", "pass_date": None}

    for i in range(pool["n"]):
        if cur is None:
            cur = new(i)
            accts.append(cur)
        a = cur
        if a["phase"] == "eval_passed":                  # funded from the day after passing
            a.update(phase="funded", P=0.0, peak=0.0, floor=-MLL, fixed=False)
        day = 0.0
        ended = None
        for j in (1, 2):
            if not pool[f"has{j}"][i] or ended:
                continue
            dpr = pool[f"dpr{j}"][i]
            cap = 40 if a["phase"] == "eval" else (20 if a["P"] < 1000 else 30 if a["P"] < 2000 else 40)
            c, rpc = contracts(dpr, cap)
            if c < 1:
                continue
            worst = c * (rpc + GAP_USD)
            if give_up and a["P"] + day - worst - RESERVE < a["floor"]:
                ended = "given up (too close to the loss limit)"
                break
            if day - worst < -DAILY_LOSS:
                continue
            if a["phase"] == "eval" and day + c * (RR * dpr - COMM - SLIP_TICKS * TICK_USD) > CONS * TARGET:
                continue
            low = a["P"] + day + c * pool[f"lo{j}"][i] * dpr - c * COMM / 2
            if low <= a["floor"]:
                ended = "failed evaluation" if a["phase"] == "eval" else "blown when funded"
                break
            day += c * (pool[f"r{j}"][i] * dpr - COMM)
        if ended:
            a.update(end=int(dkey[i]), outcome=ended)
            cur = None
            continue
        a["P"] += day
        if not a["fixed"]:
            a["peak"] = max(a["peak"], a["P"])
            a["floor"] = max(a["floor"], min(a["peak"] - MLL, LOCK))
        if a["phase"] == "eval":
            a["best"] = max(a["best"], day)
            if a["P"] >= TARGET and a["best"] <= CONS * a["P"]:
                a.update(phase="eval_passed", pass_date=int(dkey[i]))
        else:
            a["cyc"] += day
            a["win"] += day >= WIN_DAY
            amt = min(0.5 * a["P"], PAY_CAP, a["P"] - LOCK - KEEP)
            if a["win"] >= WIN_DAYS and a["cyc"] > 0 and amt >= PAY_MIN:
                a["pays"].append((int(dkey[i]), round(amt, 2)))
                a.update(P=a["P"] - amt, fixed=True, floor=LOCK, win=0, cyc=0.0)
                if len(a["pays"]) >= MAX_PAY:
                    a.update(end=int(dkey[i]), outcome="moved to live after 5 payouts")
                    cur = None
    return accts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", required=True)
    ap.add_argument("--today-vol", action="store_true")
    ap.add_argument("--trade-to-limit", action="store_true",
                    help="keep trading until the loss limit is actually hit (no halt when room < worst case + $100)")
    a = ap.parse_args()
    import warnings
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    d = il.load_instrument(a.inst, "QQQ")
    t, pool = build(d, a.today_vol)
    dk = d["dkey"]
    tr_day = t["day"].astype(int)
    comm_r = COMM / (t["dist"] * d["atr_prev"][tr_day] * lc.DPR_PER_QQQ)
    r = t["r"] - comm_r
    years = dk[tr_day] // 10000
    out = {"by_year": {}}
    print("1) TRADES (R per trade after MNQ costs)")
    print(f"{'year':6s} {'trades':>6s} {'win%':>5s} {'target%':>7s} {'avg R':>7s} {'total R':>8s} {'PF':>5s}")
    for y in list(np.unique(years)) + ["all"]:
        m = np.ones(len(r), bool) if y == "all" else years == y
        x = r[m]
        pf = x[x > 0].sum() / -x[x <= 0].sum()
        row = {"trades": int(m.sum()), "win": float((x > 0).mean()), "target": float((t["kind"][m] == 1).mean()),
               "avg_r": float(x.mean()), "total_r": float(x.sum()), "pf": float(pf)}
        out["by_year"][str(y)] = row
        print(f"{str(y):6s} {row['trades']:6d} {100 * row['win']:5.1f} {100 * row['target']:7.1f} {row['avg_r']:+7.3f} {row['total_r']:+8.1f} {pf:5.2f}")

    pnl = plain_account(pool)
    eq = START + np.cumsum(pnl)
    dd = eq - np.maximum.accumulate(eq)
    yrs = dk // 10000
    print("\n2) PLAIN ACCOUNT ($50,000, $350 risk per trade, no prop rules)")
    for y in np.unique(yrs):
        print(f"   {y}: {pnl[yrs == y].sum():+10,.0f}")
    worst_dd_end = int(np.argmin(dd))
    out["plain"] = {"total": float(pnl.sum()), "max_drawdown": float(dd.min()), "worst_day": float(pnl.min()),
                    "best_day": float(pnl.max()), "max_dd_date": int(dk[worst_dd_end]),
                    "by_year": {int(y): float(pnl[yrs == y].sum()) for y in np.unique(yrs)}}
    print(f"   total {pnl.sum():+,.0f}; max drawdown {dd.min():,.0f} (to {dk[worst_dd_end]}); worst day {pnl.min():+,.0f}; best day {pnl.max():+,.0f}")

    acc = lucid_replay(pool, dk, give_up=not a.trade_to_limit)
    fees = FEE * len(acc)
    pays = [p for x in acc for p in x["pays"]]
    net_pay = sum(p[1] * SPLIT - XFER for p in pays)
    outcomes = {}
    for x in acc:
        outcomes[x["outcome"]] = outcomes.get(x["outcome"], 0) + 1
    passed = sum(1 for x in acc if x["pass_date"])
    paid = sum(1 for x in acc if x["pays"])
    cash_y = {}
    for x in acc:
        y = x["start"] // 10000
        cash_y[y] = cash_y.get(y, 0.0) - FEE
        for dte, amt in x["pays"]:
            cash_y[dte // 10000] = cash_y.get(dte // 10000, 0.0) + amt * SPLIT - XFER
    print(f"\n3) LUCIDFLEX ACCOUNTS IN DATE ORDER ({'today' if a.today_vol else 'historical'} volatility, "
          f"{'trade until the limit' if a.trade_to_limit else 'halt when room < worst case + $100'})")
    print(f"   accounts bought {len(acc)} (${fees:,.0f}); passed evaluation {passed}; paid at least once {paid}; "
          f"payouts {len(pays)} (gross ${sum(p[1] for p in pays):,.0f}, to you ${net_pay:,.0f}); net cash {net_pay - fees:+,.0f}")
    print("   outcomes:", outcomes)
    print("   cash by year:", {k: round(v) for k, v in sorted(cash_y.items())})
    out["lucid"] = {"accounts": len(acc), "fees": fees, "passed": passed, "paid": paid, "payouts": len(pays),
                    "gross": sum(p[1] for p in pays), "to_you": net_pay, "net": net_pay - fees, "outcomes": outcomes,
                    "cash_by_year": {int(k): v for k, v in cash_y.items()},
                    "accounts_detail": [{k: x[k] for k in ("start", "end", "outcome", "pass_date", "pays")} for x in acc]}
    name = "backtest_10y_steady" + ("_todayvol" if a.today_vol else "") + ("_tolimit" if a.trade_to_limit else "") + ".json"
    (HERE / "results_round5" / name).write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
