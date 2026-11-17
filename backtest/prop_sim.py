#!/usr/bin/env python3
"""Parts 4-6: prop-firm account lifecycle simulator for NB3 V2 traded on MNQ.

What is simulated
-----------------
* Trades: NB3 V2 signals on QQQ (band 1.0, stop 0.30 x previous ATR, 1:3, first signal per day, flat
  by 15:55 ET) executed on MNQ. QQQ prices are scaled by K = NQ/QQQ (41.3, measured 41.1-41.5 on
  Sep-Nov 2026 data), so one MNQ = K x $2 = $82.6 per QQQ dollar. Slippage is charged in MNQ ticks
  (0.25 index points) on the market entry, the stop and the end-of-day exit; the target is a limit.
  Commission is charged in dollars per contract round turn.
* Sizing: contracts = floor(risk budget / (stop distance x $ per point)), capped by the firm's
  micro limit. If even one MNQ would risk more than the budget, the trade is skipped.
* Drawdown: every firm rule set is checked against the trade's intratrade path (`nb3_trades`
  minute-by-minute worst / best unrealised P&L). "eod" = threshold trails the end-of-day balance but
  is breached in real time (Topstep, Lucid, Tradeify, Alpha). "intraday" = threshold also trails
  unrealised highs (checked minute by minute, best-then-worst within a minute). "closed" = the old
  method (only closed trades checked), used only to audit the earlier estimate.
* Lifecycle: buy evaluation -> trade until pass or fail (monthly fees charged every 21 trading days)
  -> activation fee -> funded account with the firm's payout rules (eligibility, minimum, cap, split,
  what a withdrawal does to the loss limit) -> ends when the loss limit is hit, the firm moves the
  account to live (Lucid after 5 payouts), or the horizon ends. Repeated-account runs buy a new
  evaluation after each failure until the attempt budget or the horizon is used up.
* Day sequences: circular block bootstrap of the chosen period's trading days (10-day blocks, keeps
  volatility clustering and no-signal days) and chronological replay from every start day.
* Edge scenarios: a random share of target-hit trades is replaced by a randomly chosen stopped trade
  (its R and intratrade path; the day keeps its own stop distance and size) so that the expected
  gross R per trade is k x the source edge. k = 1, 0.75, 0.5, 0.25, 0 (0 = zero gross expectancy
  before costs; costs and fees then make it negative). Scenario F re-simulates the fills with
  execution stress instead.

All randomness uses fixed seeds. Usage: python3 backtest/prop_sim.py --inst <inst cache> [--n 2000]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
import zlib
from dataclasses import asdict, dataclass, field
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import intraday_lab as il  # noqa: E402
import nb3_trades as nt  # noqa: E402

K = 41.3                 # NQ / QQQ price ratio
PT = 2.0                 # MNQ dollars per index point
MNQ_TICK_Q = 0.25 / K    # one MNQ tick expressed in QQQ dollars
DAYS_PER_MONTH = 21
HORIZONS = {"3m": 63, "6m": 126, "12m": 252, "24m": 504}
BUDGETS = (1, 5, 10, 25, 50)
TRANSFER_FEE = 30.0      # assumed cost per payout transfer (Topstep's own ACH example shows $30)
RISKS = {"conservative": (150, 100), "moderate": (250, 150), "original": (350, 250),
         "aggressive": (500, 300), "very_aggressive": (750, 400)}
POLICIES = ("max_earliest", "above_cushion", "extra_buffer", "lower_funded_risk")
CUSHION = {"above_cushion": 2000.0, "extra_buffer": 3000.0}
LOWER_RISK_FACTOR = 0.6
TARGET, STOP, EOD_R, NONE = 1, 2, 3, 0


# ----------------------------------------------------------------------------
# Firm rules (verified 2026-11-17; see docs for sources and the assumptions flagged here)
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Firm:
    key: str
    name: str
    eval_fee: float                 # per purchase; if eval_monthly, charged every 21 trading days
    eval_monthly: bool
    activation: float
    funded_monthly: float           # recurring fee while funded (Alpha keeps billing)
    automation_monthly: float       # API / platform cost needed to run a bot
    commission_rt: float            # $ per MNQ round turn
    target: float = 3000.0
    dd: float = 2000.0
    eval_lock: float | None = 0.0   # profit level where the trailing floor stops (None = never)
    eval_consistency: float | None = None   # best day <= c x total profit to pass
    eval_min_days: int = 1
    eval_dll: float | None = None   # soft daily loss limit (day stops, account survives)
    max_micros: int = 50
    trail: str = "eod"              # eod | intraday | closed
    funded_lock: float | None = 0.0
    floor_after_payout: float | None = None   # None = loss limit unchanged by withdrawals
    funded_dll: float | None = None
    win_day: float = 150.0
    win_days: int = 5
    cycle_profit_positive: str = "after_first"   # after_first | always | never
    min_profit_for_payout: float = 0.0
    payout_frac: float = 0.5        # share of current profit/balance that may be requested
    payout_caps: tuple = (5000.0,)  # cap for payout n (last value repeats)
    payout_keep: float | None = None   # request at most profit - keep (Tradeify worked example)
    payout_min: float = 125.0
    funded_consistency: float | None = None   # best day in cycle <= c x cycle profit
    max_payouts: int | None = None  # then moved to live (not modelled further)
    payouts_per_month: int | None = None
    payout_every: int | None = None # audit model: fixed payout schedule in trading days
    split: float = 0.9
    exact_sizing: bool = False      # audit model: fractional contracts
    bot: str = ""
    croatia: str = ""


FIRMS = {
    "topstep": Firm(
        "topstep", "Topstep 50K Trading Combine (with DLL) -> XFA Standard", 49.0, True, 149.0, 0.0, 29.0, 1.22,
        eval_lock=0.0, eval_consistency=0.55, eval_min_days=2, eval_dll=1000.0, max_micros=50,
        funded_lock=0.0, floor_after_payout=0.0, funded_dll=1000.0, win_day=150.0, win_days=5,
        cycle_profit_positive="after_first", payout_frac=0.5, payout_caps=(10000.0,), payout_min=125.0,
        bot="allowed via TopstepX API from a personal device only (no VPS/VPN)", croatia="eligible (OFAC list only)"),
    "lucid": Firm(
        "lucid", "Lucid LucidFlex 50K (no DLL, 40% consistency)", 130.0, False, 0.0, 0.0, 0.0, 1.50,
        eval_lock=100.0, eval_consistency=0.40, eval_min_days=1, max_micros=40,
        funded_lock=100.0, floor_after_payout=100.0, win_day=150.0, win_days=5, cycle_profit_positive="always",
        payout_frac=0.5, payout_caps=(2000.0,), payout_min=500.0, max_payouts=5,
        bot="automated systems permitted (help centre); LucidDirect agreement requires written approval",
        croatia="eligible (not on restricted list dated 2026-10-08)"),
    "tradeify": Firm(
        "tradeify", "Tradeify Growth 50K", 145.0, False, 0.0, 0.0, 0.0, 1.50,
        eval_lock=None, eval_consistency=None, eval_min_days=1, eval_dll=1250.0, max_micros=40,
        funded_lock=100.0, floor_after_payout=None, funded_dll=1250.0, win_day=150.01, win_days=5,
        cycle_profit_positive="never", min_profit_for_payout=3000.0, payout_frac=1.0,
        payout_caps=(1500.0, 2000.0, 2500.0, 3000.0), payout_keep=600.0, payout_min=500.0, funded_consistency=0.35,
        bot="personal bots allowed with proof of sole ownership; no HFT; no multi-firm bot services",
        croatia="sim-funded only (help page, not re-fetchable)"),
    "alpha": Firm(
        "alpha", "Alpha Futures Standard 50K (manual execution only)", 129.0, True, 0.0, 129.0, 0.0, 1.50,
        eval_lock=0.0, eval_consistency=0.50, eval_min_days=2, max_micros=50,
        funded_lock=0.0, floor_after_payout=None, funded_dll=1000.0, win_day=200.0, win_days=5,
        cycle_profit_positive="never", payout_frac=0.5, payout_caps=(3000.0,), payout_min=500.0,
        funded_consistency=0.40, payouts_per_month=4,
        bot="bots / full automation prohibited; indicator + manual execution allowed", croatia="not verified"),
    "audit_old": Firm(
        "audit_old", "Earlier estimate's generic rules ($130, closed-trade drawdown)", 130.0, False, 0.0, 0.0, 0.0, 0.0,
        eval_lock=0.0, max_micros=10**6, trail="closed", funded_lock=0.0, payout_every=15, payout_min=0.0,
        payout_caps=(10**9,), exact_sizing=True, bot="n/a", croatia="n/a"),
    "audit_fixed": Firm(
        "audit_fixed", "Same generic rules, corrected method (MNQ sizing, intratrade breach)", 130.0, False, 0.0, 0.0, 0.0, 1.50,
        eval_lock=0.0, max_micros=50, trail="eod", funded_lock=0.0, payout_every=15, payout_min=0.0,
        payout_caps=(10**9,), bot="n/a", croatia="n/a"),
    "topstep_intraday": Firm(
        "topstep_intraday", "Sensitivity: Topstep rules with intraday trailing", 49.0, True, 149.0, 0.0, 29.0, 1.22,
        eval_lock=0.0, eval_consistency=0.55, eval_min_days=2, eval_dll=1000.0, max_micros=50, trail="intraday",
        funded_lock=0.0, floor_after_payout=0.0, funded_dll=1000.0, payout_caps=(10000.0,),
        bot="n/a", croatia="n/a"),
}


# ----------------------------------------------------------------------------
# Trade pool (one row per trading day of the source period)
# ----------------------------------------------------------------------------
def build_pool(d: dict, a: int, b: int, ex: nt.Exec, seed: int = 7) -> dict:
    tr = nt.extract(d, ex=ex, rng=np.random.default_rng(seed))
    by = {t.dkey: t for t in tr}
    days = [int(k) for k in d["dkey"] if a <= k <= b]
    n = len(days)
    pool = {"dkey": np.array(days), "has": np.zeros(n, bool), "dpr": np.full(n, np.nan), "r": np.zeros(n),
            "rg": np.zeros(n), "lo": np.zeros(n), "reason": np.zeros(n, np.int8), "hi_path": [None] * n,
            "lo_path": [None] * n}
    code = {"TARGET": TARGET, "STOP": STOP, "STOPGAP": STOP, "EOD": EOD_R}
    for j, k in enumerate(days):
        t = by.get(k)
        if t is None:
            continue
        pool["has"][j] = True
        pool["dpr"][j] = t.dist * K * PT           # dollars per R per MNQ contract
        pool["r"][j], pool["rg"][j] = t.r_net, t.r_gross
        pool["lo"][j] = min(0.0, float(t.path_lo.min()))
        pool["reason"][j] = code[t.reason]
        pool["hi_path"][j], pool["lo_path"][j] = t.path_hi.astype(np.float64), t.path_lo.astype(np.float64)
    return pool


def conversion_share(pool: dict, k: float) -> float:
    """Share of target trades to replace by stopped trades so mean gross R becomes k x source."""
    h = pool["has"]
    rg, rs = pool["rg"][h], pool["reason"][h]
    mu, p_t = rg.mean(), (rs == TARGET).mean()
    g_t, g_s = rg[rs == TARGET].mean(), rg[rs == STOP].mean()
    return float(np.clip((1 - k) * mu / (p_t * (g_t - g_s)), 0, 1))


def make_streams(pool: dict, n: int, horizon: int, method: str, block: int, k: float, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    N = len(pool["dkey"])
    if method == "replay":
        idx = (np.arange(N)[:, None] + np.arange(horizon)[None, :]) % N
    else:
        nb = math.ceil(horizon / block)
        st = rng.integers(0, N, size=(n, nb))
        idx = ((st[:, :, None] + np.arange(block)[None, None, :]) % N).reshape(n, -1)[:, :horizon]
    src = idx.copy()
    f = conversion_share(pool, k) if k < 1 else 0.0
    if f > 0:
        stops = np.flatnonzero(pool["has"] & (pool["reason"] == STOP))
        conv = (pool["reason"][idx] == TARGET) & (rng.random(idx.shape) < f)
        src = np.where(conv, stops[rng.integers(0, len(stops), idx.shape)], idx)
    return {"idx": idx.astype(np.int32), "src": src.astype(np.int32), "conv_share": f}


def day_arrays(pool: dict, streams: dict, firm: Firm, risk: float, dll: float | None) -> tuple:
    """Per stream-day closed P&L, worst intraday P&L (both $, relative to the day's start) and size."""
    idx, src = streams["idx"], streams["src"]
    dpr = pool["dpr"][idx]
    has = pool["has"][idx]
    with np.errstate(invalid="ignore", divide="ignore"):
        if firm.exact_sizing:
            c = np.where(has, risk / dpr, 0.0)
        else:
            c = np.where(has, np.minimum(np.floor(risk / dpr + 1e-9), firm.max_micros), 0.0)
    c = np.nan_to_num(c)
    pnl = c * (pool["r"][src] * np.nan_to_num(dpr)) - c * firm.commission_rt
    low = c * (pool["lo"][src] * np.nan_to_num(dpr)) - c * firm.commission_rt / 2
    if dll is not None:
        hit = low <= -dll
        pnl = np.where(hit, -dll, pnl)
        low = np.where(hit, -dll, low)
    return pnl, low, c > 0, c, np.nan_to_num(dpr)


# ----------------------------------------------------------------------------
# One stream: sequential attempts until the budget or the horizon is used up
# ----------------------------------------------------------------------------
def _intraday_breach(pool, src_j, c, dpr, P, peak, dd, lock):
    """Minute-by-minute intraday-trailing check. Returns (breached, new intraday peak)."""
    his, los = pool["hi_path"][src_j], pool["lo_path"][src_j]
    for hh, ll in zip(his, los):
        peak = max(peak, P + c * dpr * hh)
        thr = peak - dd if lock is None else min(peak - dd, lock)
        if P + c * dpr * ll <= thr:
            return True, peak
    return False, peak


def run_stream(firm: Firm, E: tuple, F: tuple, horizon: int, max_attempts: int, policy: str,
               pool: dict | None = None, src: np.ndarray | None = None) -> tuple[list, np.ndarray]:
    e_pnl, e_low, e_tr, e_c, dpr = (x.tolist() for x in E)
    f_pnl, f_low, f_tr, f_c, _ = (x.tolist() for x in F)
    srcl = src.tolist() if src is not None else None
    cash = np.zeros(horizon)
    attempts = []
    t, dd = 0, firm.dd
    intraday = firm.trail == "intraday"
    while t < horizon and len(attempts) < max_attempts:
        s = t
        rec = {"start": s, "fees": 0.0, "passed": False, "days_to_pass": None, "payouts": [], "net_payouts": 0.0,
               "funded_days": 0, "end": "horizon", "end_day": horizon - 1, "first_payout_day": None}

        def charge(x, day):
            cash[day] -= x
            rec["fees"] += x

        # ---------------- evaluation ----------------
        P = peak = best = 0.0
        ipeak = 0.0
        floor = -dd
        days = 0
        passed = failed = False
        while t < horizon:
            el = t - s
            if el % DAYS_PER_MONTH == 0:
                if el == 0 or firm.eval_monthly:
                    charge(firm.eval_fee, t)
                if firm.automation_monthly:
                    charge(firm.automation_monthly, t)
            if e_tr[t]:
                if intraday:
                    br, ipeak = _intraday_breach(pool, srcl[t], e_c[t], dpr[t], P, max(ipeak, P), dd, firm.eval_lock)
                elif firm.trail == "closed":
                    br = P + e_pnl[t] <= floor
                else:
                    br = P + e_low[t] <= floor
                if br:
                    failed = True
                    break
                P += e_pnl[t]
                days += 1
                best = max(best, e_pnl[t])
                peak = max(peak, P)
                if intraday:
                    ipeak = max(ipeak, P)
                    tp = ipeak
                else:
                    tp = peak
                floor = tp - dd if firm.eval_lock is None else min(tp - dd, firm.eval_lock)
                if P >= firm.target and days >= firm.eval_min_days and (
                        firm.eval_consistency is None or best <= firm.eval_consistency * P):
                    passed = True
                    break
            t += 1
        if failed or not passed:
            rec["end"] = "eval_failed" if failed else "horizon"
            rec["end_day"] = min(t, horizon - 1)
            attempts.append(rec)
            t += 1
            continue
        rec["passed"], rec["days_to_pass"] = True, t - s + 1
        if firm.activation:
            charge(firm.activation, t)
        t += 1
        # ---------------- funded ----------------
        fs = t
        P = peak = ipeak = 0.0
        floor, fixed = -dd, None
        cyc_win, cyc_profit, cyc_best, n_pay = 0, 0.0, 0.0, 0
        pay_days: list[int] = []
        last_pay = fs
        mult_ok = True
        ended = False
        while t < horizon:
            el = t - s
            if el % DAYS_PER_MONTH == 0:
                if firm.funded_monthly:
                    charge(firm.funded_monthly, t)
                if firm.automation_monthly:
                    charge(firm.automation_monthly, t)
            if f_tr[t]:
                if intraday:
                    lock = fixed if fixed is not None else firm.funded_lock
                    if fixed is not None:
                        br = P + f_low[t] <= fixed
                    else:
                        br, ipeak = _intraday_breach(pool, srcl[t], f_c[t], dpr[t], P, max(ipeak, P), dd, lock)
                elif firm.trail == "closed":
                    br = P + f_pnl[t] <= floor
                else:
                    br = P + f_low[t] <= floor
                if br:
                    rec["end"], rec["end_day"] = "blown", t
                    ended = True
                    rec["funded_days"] = t - fs + 1
                    t += 1
                    break
                pnl = f_pnl[t]
                P += pnl
                cyc_profit += pnl
                cyc_best = max(cyc_best, pnl)
                if pnl >= firm.win_day:
                    cyc_win += 1
                peak = max(peak, P)
                if intraday:
                    ipeak = max(ipeak, P)
                if fixed is None:
                    tp = ipeak if intraday else peak
                    floor = tp - dd if firm.funded_lock is None else min(tp - dd, firm.funded_lock)
                else:
                    floor = fixed
            # ---- payout decision at the end of the day ----
            amount = 0.0
            if firm.payout_every is not None:
                if t - last_pay + 1 >= firm.payout_every:
                    keep = CUSHION.get(policy, 2000.0)
                    amount = max(0.0, P - max(floor, 0.0) - keep)
                    last_pay = t + 1
            else:
                eligible = cyc_win >= firm.win_days and P >= firm.min_profit_for_payout and P > 0
                if firm.cycle_profit_positive == "always" or (firm.cycle_profit_positive == "after_first" and n_pay):
                    eligible = eligible and cyc_profit > 0
                if firm.funded_consistency is not None:
                    eligible = eligible and cyc_profit > 0 and cyc_best <= firm.funded_consistency * cyc_profit
                if firm.payouts_per_month is not None:
                    eligible = eligible and sum(1 for x in pay_days if t - x < DAYS_PER_MONTH) < firm.payouts_per_month
                if eligible:
                    cap = firm.payout_caps[min(n_pay, len(firm.payout_caps) - 1)]
                    mx = min(firm.payout_frac * P, cap)
                    if firm.payout_keep is not None:
                        mx = min(mx, P - firm.payout_keep)
                    if policy in CUSHION:
                        post_floor = firm.floor_after_payout if firm.floor_after_payout is not None else floor
                        mx = min(mx, P - post_floor - CUSHION[policy])
                    if mx >= max(firm.payout_min, 1.0):
                        amount = mx
            if amount > 0:
                net = amount * firm.split - TRANSFER_FEE
                cash[t] += net
                rec["payouts"].append(amount)
                rec["net_payouts"] += net
                if rec["first_payout_day"] is None:
                    rec["first_payout_day"] = t
                P -= amount
                n_pay += 1
                pay_days.append(t)
                cyc_win, cyc_profit, cyc_best = 0, 0.0, 0.0
                if firm.floor_after_payout is not None:
                    fixed = floor = firm.floor_after_payout
                if firm.max_payouts is not None and n_pay >= firm.max_payouts:
                    rec["end"], rec["end_day"] = "moved_live", t
                    rec["funded_days"] = t - fs + 1
                    ended = True
                    t += 1
                    break
            t += 1
        if not ended:
            rec["funded_days"] = horizon - fs
            rec["end_day"] = horizon - 1
            rec["open_balance"] = P
        attempts.append(rec)
    return attempts, cash


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------
def pct(x, q):
    return float(np.percentile(x, q)) if len(x) else float("nan")


def lifecycle_metrics(first: list[dict]) -> dict:
    n = len(first)
    fees = np.array([r["fees"] for r in first])
    netp = np.array([r["net_payouts"] for r in first])
    gross = np.array([sum(r["payouts"]) for r in first])
    npay = np.array([len(r["payouts"]) for r in first])
    profit = netp - fees
    passed = [r for r in first if r["passed"]]
    eval_cost = np.array([r["fees"] if not r["passed"] else np.nan for r in first])
    allp = [p for r in first for p in r["payouts"]]
    fdays = np.array([r["funded_days"] for r in passed]) if passed else np.array([])
    p_first = float(np.mean([bool(r["payouts"]) for r in first]))
    return {
        "lifecycles": n,
        "pass_prob": len(passed) / n,
        "median_days_to_pass": pct([r["days_to_pass"] for r in passed], 50) if passed else float("nan"),
        "p_pass_1_month": float(np.mean([r["passed"] and r["days_to_pass"] <= DAYS_PER_MONTH for r in first])),
        "p_pass_2_months": float(np.mean([r["passed"] and r["days_to_pass"] <= 2 * DAYS_PER_MONTH for r in first])),
        "mean_fees_per_attempt": float(fees.mean()),
        "mean_fees_failed_eval": float(np.nanmean(eval_cost)) if np.isfinite(eval_cost).any() else float("nan"),
        "p_first_payout": p_first,
        "funded_lifespan_mean_days": float(fdays.mean()) if len(fdays) else float("nan"),
        "funded_lifespan_median_days": pct(fdays, 50) if len(fdays) else float("nan"),
        "p_blown_funded": float(np.mean([r["end"] == "blown" for r in passed])) if passed else float("nan"),
        "p_moved_live": float(np.mean([r["end"] == "moved_live" for r in first])),
        "mean_payouts": float(npay.mean()),
        "median_payout": pct(allp, 50) if allp else float("nan"),
        "mean_gross_payouts": float(gross.mean()),
        "mean_net_payouts": float(netp.mean()),
        "mean_net_profit": float(profit.mean()),
        "median_net_profit": pct(profit, 50),
        "p5_net_profit": pct(profit, 5),
        "p95_net_profit": pct(profit, 95),
        "max_loss": float(profit.min()),
        "max_gain": float(profit.max()),
        "p_profit": float((profit > 0).mean()),
        "p_loss": float((profit < 0).mean()),
        "profit_per_fee_dollar": float(profit.mean() / fees.mean()) if fees.mean() > 0 else float("nan"),
        "attempts_per_payout": 1 / p_first if p_first > 0 else float("inf"),
    }


def budget_metrics(streams_out: list[tuple[list, np.ndarray]]) -> list[dict]:
    rows = []
    cums = [np.cumsum(c) for _, c in streams_out]
    for B in BUDGETS:
        for hname, h in HORIZONS.items():
            net, need, wdd, exh, lost, pays = [], [], [], [], [], []
            for (att, cash), cum in zip(streams_out, cums):
                H = min(h, len(cum))
                endB = att[B - 1]["end_day"] if len(att) >= B else len(cum) - 1
                stop = min(H, endB + 1)
                cs = cum[:stop] if stop > 0 else np.zeros(1)
                net.append(cs[-1])
                fp = [a["first_payout_day"] for a in att[:B] if a["first_payout_day"] is not None and a["first_payout_day"] < stop]
                upto = cs[: (min(fp) + 1)] if fp else cs
                need.append(-min(0.0, upto.min()))
                run_max = np.maximum.accumulate(np.r_[0.0, cs])
                wdd.append(float((np.r_[0.0, cs] - run_max).min()))
                done = len(att) >= B and att[B - 1]["end"] != "horizon" and att[B - 1]["end_day"] < H
                exh.append(done)
                lost.append(done and not fp)
                pays.append(bool(fp))
            net = np.array(net)
            rows.append({"budget": B, "horizon": hname, "mean_net": float(net.mean()), "median_net": pct(net, 50),
                         "p5_net": pct(net, 5), "p95_net": pct(net, 95), "worst_net": float(net.min()),
                         "p_profit": float((net > 0).mean()), "p_any_payout": float(np.mean(pays)),
                         "cash_before_first_payout_median": pct(need, 50), "cash_before_first_payout_p95": pct(need, 95),
                         "worst_cash_drawdown_median": pct(wdd, 50), "worst_cash_drawdown_p5": pct(wdd, 5),
                         "p_budget_exhausted": float(np.mean(exh)), "p_budget_lost_no_payout": float(np.mean(lost)),
                         "mean_monthly_cashflow": float(net.mean() / (h / DAYS_PER_MONTH))})
    return rows


# ----------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------
SCENARIOS = {  # name: (pool key, k)
    "A_oos_edge": ("base", 1.0), "B_75pct_edge": ("base", 0.75), "C_50pct_edge": ("base", 0.5),
    "D_25pct_edge": ("base", 0.25), "E_no_edge": ("base", 0.0), "F_exec_stress": ("stress", 1.0),
}
# Sensitivity: 2025-26 trades with stops scaled to Sep-Nov 2026 volatility (median one-MNQ stop $275
# vs $215 in the holdout; nb3_futures.py), i.e. fewer contracts fit a given risk budget.
CURVOL_SCALE = 275.3 / 215.0
EXTRA_SCENARIOS = {"G_current_vol_A": ("curvol", 1.0), "H_current_vol_B": ("curvol", 0.75)}
EXEC_BASE = nt.Exec(slip_ticks=1, tick=MNQ_TICK_Q, commission=0.0)
EXEC_STRESS = nt.Exec(slip_ticks=3, tick=MNQ_TICK_Q, commission=0.0, entry_delay_bars=1,
                      target_through_ticks=1, miss_prob=0.05)

_G: dict = {}


def _init(pools, streams):
    _G["pools"], _G["streams"] = pools, streams


def job(args):
    firm_key, scen, method, risk_name, policy, horizon, max_att = args
    firm = FIRMS[firm_key]
    if firm_key == "audit_old":
        pool_key = "audit"
    elif scen == "A_full_history":
        pool_key = "full"
    else:
        pool_key = {**SCENARIOS, **EXTRA_SCENARIOS}[scen][0]
    pool = _G["pools"][pool_key]
    st = _G["streams"][(scen, method, pool_key)]
    er, fr = RISKS[risk_name]
    if policy == "lower_funded_risk":
        fr = fr * LOWER_RISK_FACTOR
    E = day_arrays(pool, st, firm, er, firm.eval_dll)
    F = day_arrays(pool, st, firm, fr, firm.funded_dll)
    outs = []
    for i in range(st["idx"].shape[0]):
        Ei = tuple(x[i] for x in E)
        Fi = tuple(x[i] for x in F)
        outs.append(run_stream(firm, Ei, Fi, horizon, max_att, policy, pool, st["src"][i]))
    first = [a[0] for a, _ in outs if a]
    life = lifecycle_metrics(first)
    trade_days = E[2].mean()
    tr_e = float(E[2].mean() / max(pool["has"][st["idx"]].mean(), 1e-9))
    tr_f = float(F[2].mean() / max(pool["has"][st["idx"]].mean(), 1e-9))
    gross_r = float(np.mean(pool["rg"][st["src"]][pool["has"][st["idx"]]]))
    net_r = float(np.mean(pool["r"][st["src"]][pool["has"][st["idx"]]]))
    sized = E[2]
    gross_usd = float((E[3] * pool["rg"][st["src"]] * E[4])[sized].mean()) if sized.any() else float("nan")
    net_usd = float(E[0][sized].mean()) if sized.any() else float("nan")
    key = {"firm": firm_key, "scenario": scen, "method": method, "risk": risk_name, "policy": policy}
    info = {"eval_trade_share": tr_e, "funded_trade_share": tr_f, "mean_gross_r": gross_r, "mean_r_after_slippage": net_r,
            "trade_days_per_day": float(trade_days), "conv_share": st["conv_share"],
            "eval_gross_usd_per_trade": gross_usd, "eval_net_usd_per_trade": net_usd}
    budget = [{**key, **row} for row in budget_metrics(outs)] if max_att > 1 else []
    return {**key, **info, **life}, budget


def run_jobs(jobs, pools, streams, out: Path, suffix: str, procs: int, t0: float) -> None:
    print(f"{len(jobs)} jobs, pools built in {time.time() - t0:.0f}s", flush=True)
    out.mkdir(parents=True, exist_ok=True)
    life_rows, budget_rows = [], []
    with Pool(procs, initializer=_init, initargs=(pools, streams)) as p:
        for i, (life, bud) in enumerate(p.imap_unordered(job, jobs, chunksize=2)):
            life_rows.append(life); budget_rows.extend(bud)
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(jobs)}  {time.time() - t0:.0f}s", flush=True)
    for name, rows in ((f"lifecycles{suffix}.csv", life_rows), (f"budgets{suffix}.csv", budget_rows)):
        rows.sort(key=lambda r: tuple(str(r[k]) for k in ("firm", "scenario", "method", "risk", "policy")))
        with open(out / name, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", required=True)
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--block", type=int, default=10)
    ap.add_argument("--out", default="backtest/results_props")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--curvol", action="store_true", help="only run the current-volatility sensitivity")
    args = ap.parse_args()
    t0 = time.time()
    d = il.load_instrument(args.inst, "QQQ")
    HO = (20250101, 20260331)
    pools = {"base": build_pool(d, *HO, EXEC_BASE), "stress": build_pool(d, *HO, EXEC_STRESS),
             "full": build_pool(d, 0, 20260331, EXEC_BASE),
             "audit": build_pool(d, 0, 20260331, nt.Exec())}      # earlier estimate: QQQ costs, full history
    H = HORIZONS["24m"]
    if args.curvol:
        cv = dict(pools["base"]); cv["dpr"] = pools["base"]["dpr"] * CURVOL_SCALE
        pools = {"curvol": cv}
        streams = {(sc, "bootstrap", "curvol"): make_streams(cv, args.n, H, "bootstrap", args.block, k,
                                                             zlib.crc32(f"{sc}|bootstrap".encode()))
                   for sc, (_, k) in EXTRA_SCENARIOS.items()}
        jobs = [(f, sc, "bootstrap", r, pol, H, 50) for f in ("topstep", "lucid", "tradeify", "alpha")
                for sc in EXTRA_SCENARIOS for r in RISKS for pol in ("max_earliest", "above_cushion")]
        run_jobs(jobs, pools, streams, Path(args.out), "_curvol", args.procs, t0)
        return
    streams = {}
    for scen, (pk, k) in SCENARIOS.items():
        for method in ("bootstrap", "replay"):
            seed = zlib.crc32(f"{scen}|{method}".encode())
            streams[(scen, method, pk)] = make_streams(pools[pk], args.n, H, method, args.block, k, seed)
    streams[("A_full_history", "bootstrap", "full")] = make_streams(pools["full"], args.n, H, "bootstrap", args.block, 1.0, 11)
    streams[("A_full_history", "replay", "full")] = make_streams(pools["full"], args.n, H, "replay", args.block, 1.0, 12)
    streams[("A_full_history", "iid", "audit")] = make_streams(pools["audit"], args.n, H, "bootstrap", 1, 1.0, 13)
    streams[("A_full_history", "bootstrap", "audit")] = streams[("A_full_history", "iid", "audit")]

    jobs = []
    main_firms = ("topstep", "lucid", "tradeify", "alpha")
    for firm in main_firms:
        for scen in SCENARIOS:
            for method in ("bootstrap", "replay"):
                for risk in RISKS:
                    for pol in POLICIES:
                        if method == "replay" and pol != "max_earliest":
                            continue
                        jobs.append((firm, scen, method, risk, pol, H, 50))
    for firm in main_firms:
        for risk in RISKS:
            jobs.append((firm, "A_full_history", "bootstrap", risk, "max_earliest", H, 50))
    for risk in RISKS:   # audit of the earlier estimate and the intraday-trailing sensitivity
        jobs.append(("audit_old", "A_full_history", "iid", risk, "above_cushion", H, 1))
        jobs.append(("audit_fixed", "A_full_history", "bootstrap", risk, "above_cushion", H, 1))
        jobs.append(("audit_fixed", "A_oos_edge", "bootstrap", risk, "above_cushion", H, 1))
        jobs.append(("audit_fixed", "E_no_edge", "bootstrap", risk, "above_cushion", H, 1))
        jobs.append(("topstep_intraday", "A_oos_edge", "bootstrap", risk, "max_earliest", H, 1))
    out = Path(args.out)
    run_jobs(jobs, pools, streams, out, "", args.procs, t0)
    meta = {"K": K, "block": args.block, "n_bootstrap": args.n, "horizon_days": H, "transfer_fee": TRANSFER_FEE,
            "exec_base": asdict(EXEC_BASE), "exec_stress": asdict(EXEC_STRESS),
            "pool_days": {k: int(len(v["dkey"])) for k, v in pools.items()},
            "pool_trades": {k: int(v["has"].sum()) for k, v in pools.items()},
            "pool_mean_gross_r": {k: float(v["rg"][v["has"]].mean()) for k, v in pools.items()},
            "pool_mean_r_after_slippage": {k: float(v["r"][v["has"]].mean()) for k, v in pools.items()},
            "stop_dollars_per_mnq_pct": {k: [float(x) for x in np.nanpercentile(v["dpr"][v["has"]], [5, 25, 50, 75, 95])] for k, v in pools.items()},
            "conversion_share": {s: streams[(s, "bootstrap", pk)]["conv_share"] for s, (pk, _) in SCENARIOS.items()},
            "firms": {k: asdict(v) for k, v in FIRMS.items()}, "seconds": time.time() - t0}
    (out / "meta.json").write_text(json.dumps(meta, indent=1, default=float))
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
