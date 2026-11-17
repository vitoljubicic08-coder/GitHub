#!/usr/bin/env python3
"""Round 5: Lucid Flex 50K ($130 one-time) — which NB3 exit, sizing and payout policy gets paid most often?

Rules (prop_sim.FIRMS["lucid"], verified 2026-11-17):
  evaluation  +$3,000 target; $2,000 loss limit trailing the end-of-day high but breached in real
              time (open P&L counts), stops trailing at +$100; best day <= 40% of profit to pass;
              no daily loss limit; at most 40 micros.
  funded      same loss limit (stops at +$100, fixed at +$100 after the first payout); payout when
              the cycle has >= 5 days of +$150 and positive cycle profit: up to 50% of profit, at
              most $2,000, at least $500; 90% split; after 5 payouts the account moves to live
              (not modelled further). $30 assumed per transfer.

Simulation: per-day trade pools from lab4.bracket on QQQ executed as MNQ (one MNQ tick of slippage
per market/stop fill, $1.50 per round turn, $ per QQQ dollar = 41.3 x $2); 10-day block bootstrap of
the period's trading days; every lifecycle starts with a new $130 account. Vectorised over lifecycles
(`simulate`), checked against prop_sim.run_stream for budget sizing (`tests/test_lucid5.py`).

Sizing modes: ("budget", $) contracts = floor($ / risk per MNQ); ("cush", f) contracts =
floor(f x (balance - loss limit) / risk per MNQ). 0 contracts = the trade is skipped. Cap 40.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lab4  # noqa: E402
import prop_sim as ps  # noqa: E402

LUCID = ps.FIRMS["lucid"]
DPR_PER_QQQ = ps.K * ps.PT          # MNQ dollars per QQQ dollar per contract
COMM = LUCID.commission_rt


@dataclass(frozen=True)
class Config:
    stop: float = 0.3
    rr: float = 3.0
    mt: int = 1
    eval_size: tuple = ("budget", 350.0)
    funded_size: tuple = ("budget", 250.0)
    keep: float = 0.0               # keep at least this much above the post-payout loss limit


def build_pool(d: dict, start: int, end: int, stop: float, rr: float, mt: int) -> dict:
    """Per trading day of [start, end]: up to `mt` NB3 trades (R after slippage, before commission)."""
    dd = lab4.subset(d, start, end)
    sig, _ = lab4.signals4(dd, "nb3", ("none", "first" if mt == 1 else "pass"))
    t = lab4.bracket(dd, sig, stop, rrs=(rr,), max_trades=mt, slip=ps.MNQ_TICK_Q, commission=0.0)[rr]
    return pool_from_trades(dd, t)


def pool_from_trades(dd: dict, t: dict) -> dict:
    """Day-indexed pool (at most 2 trades per day, in exit order) from a bracket result on `dd`."""
    n = len(dd["dkey"])
    pool = {"dkey": dd["dkey"], "n": n}
    for j in (1, 2):
        for k in ("has", "r", "lo", "dpr", "kind"):
            pool[f"{k}{j}"] = np.zeros(n, bool) if k == "has" else np.zeros(n)
    order = np.lexsort((t["exit"], t["day"]))
    slot = np.zeros(n, int)
    for i in order:
        day = int(t["day"][i])
        j = slot[day] + 1
        if j > 2:
            continue
        slot[day] = j
        pool[f"has{j}"][day] = True
        pool[f"r{j}"][day] = t["r"][i]
        pool[f"lo{j}"][day] = t["lo"][i]
        pool[f"kind{j}"][day] = t["kind"][i]
        pool[f"dpr{j}"][day] = t["dist"][i] * dd["atr_prev"][day] * DPR_PER_QQQ
    return pool


def streams(pool: dict, n: int, horizon: int, block: int = 10, seed: int = 0, edge_keep: float = 1.0) -> dict:
    """Block-bootstrap day indices; edge_keep < 1 turns a random share of target trades into stops so the
    pool's mean gross R becomes edge_keep x its own (the stop trade's R/low are the pool's median stop)."""
    rng = np.random.default_rng(seed)
    N = pool["n"]
    nb = math.ceil(horizon / block)
    st = rng.integers(0, N, size=(n, nb))
    idx = ((st[:, :, None] + np.arange(block)[None, None, :]) % N).reshape(n, -1)[:, :horizon]
    out = {"idx": idx, "conv1": np.zeros(idx.shape, bool), "conv2": np.zeros(idx.shape, bool)}
    if edge_keep < 1:
        has = np.r_[pool["r1"][pool["has1"]], pool["r2"][pool["has2"]]]
        kind = np.r_[pool["kind1"][pool["has1"]], pool["kind2"][pool["has2"]]]
        stop_r = float(np.median(has[kind == 0]))
        tgt_r = float(np.mean(has[kind == 1]))
        f = float(np.clip((1 - edge_keep) * has.mean() / ((kind == 1).mean() * (tgt_r - stop_r)), 0, 1))
        out["conv1"] = (pool["kind1"][idx] == 1) & (rng.random(idx.shape) < f)
        out["conv2"] = (pool["kind2"][idx] == 1) & (rng.random(idx.shape) < f)
        out["stop_r"], out["share"] = stop_r, f
    return out


SCALING_50K = ((1000.0, 20), (2000.0, 30), (float("inf"), 40))   # funded profit tier -> max micros


def funded_cap(profit):
    """LucidFlex 50K funded scaling plan (help centre, checked 2026-11-17), from the session's start profit."""
    return np.where(profit < 1000.0, 20, np.where(profit < 2000.0, 30, 40))


def _contracts(mode, cushion, dpr, cap=None):
    with np.errstate(invalid="ignore", divide="ignore"):
        risk = mode[1] if mode[0] == "budget" else mode[1] * cushion
        c = np.floor(risk / dpr + 1e-9)
    return np.clip(np.nan_to_num(c), 0, LUCID.max_micros if cap is None else cap)


def _day(pool, st, t, mode, cushion, cap=None):
    """Closed P&L and worst intraday P&L ($) of every lifecycle's day t."""
    idx = st["idx"][:, t]
    pnl = np.zeros(len(idx))
    low = np.zeros(len(idx))
    for j in (1, 2):
        has = pool[f"has{j}"][idx]
        if not has.any():
            continue
        dpr = pool[f"dpr{j}"][idx]
        r, lo = pool[f"r{j}"][idx], pool[f"lo{j}"][idx]
        if f"conv{j}" in st and st[f"conv{j}"][:, t].any():
            cv = st[f"conv{j}"][:, t]
            r = np.where(cv, st["stop_r"], r)
            lo = np.where(cv, st["stop_r"], lo)
        c = np.where(has, _contracts(mode, cushion, np.where(has, dpr, 1.0), cap), 0.0)
        low = np.minimum(low, pnl + c * lo * dpr - c * COMM / 2)
        pnl = pnl + c * r * dpr - c * COMM
    return pnl, low


def simulate(pool: dict, st: dict, cfg: Config, horizon: int | None = None, max_accounts: int = 1,
             scaling_plan: bool = False, snapshots: tuple = ()) -> dict:
    """max_accounts > 1: when an account ends (failed, blown or moved to live) a new $130 account is
    bought and started the next trading day, until that many accounts have been bought."""
    idx = st["idx"]
    n, H = idx.shape
    H = H if horizon is None else min(H, horizon)
    fee = LUCID.eval_fee
    accounts = np.ones(n, int); fees = np.full(n, fee); cash_min = -fees.copy()
    npay_acc = np.zeros(n, int)
    snap = {}
    first_acc = np.zeros(n, int)                 # which account produced the first payout (0 = none)
    cash_first = np.zeros(n)                     # cash spent on accounts when the first payout arrives
    first_amt = np.zeros(n)                      # gross amount of the first payout
    phase = np.zeros(n, int)                    # 0 eval, 1 funded, 2 done
    P = np.zeros(n); peak = np.zeros(n); best = np.zeros(n)
    floor = np.full(n, -LUCID.dd)
    fixed = np.zeros(n, bool)
    cyc_win = np.zeros(n, int); cyc_p = np.zeros(n); npay = np.zeros(n, int)
    pass_day = np.full(n, -1); first_pay = np.full(n, -1); end = np.zeros(n, int)   # 1 failed 2 blown 3 live
    gross = np.zeros(n); net = np.zeros(n)
    start_funded = np.zeros(n, bool)
    for t in range(H):
        if t in snapshots:
            snap[t] = net - fees
        # accounts that passed yesterday start funded today
        if start_funded.any():
            s = start_funded
            phase[s] = 1
            P[s] = peak[s] = 0.0
            floor[s] = -LUCID.dd
            start_funded[:] = False
        if max_accounts > 1:
            rs = (phase == 2) & (accounts < max_accounts)
            if rs.any():
                phase[rs] = 0
                P[rs] = peak[rs] = best[rs] = cyc_p[rs] = 0.0
                floor[rs] = -LUCID.dd
                fixed[rs] = False
                cyc_win[rs] = npay_acc[rs] = 0
                accounts[rs] += 1
                fees[rs] += fee
                cash_min = np.minimum(cash_min, net - fees)
        live = phase < 2
        if not live.any():
            break
        ev, fu = phase == 0, phase == 1
        pnl = np.zeros(n); low = np.zeros(n)
        if ev.any():
            pe, le = _day(pool, st, t, cfg.eval_size, P - floor)
            pnl = np.where(ev, pe, pnl); low = np.where(ev, le, low)
        if fu.any():
            pf, lf = _day(pool, st, t, cfg.funded_size, P - floor, funded_cap(P) if scaling_plan else None)
            pnl = np.where(fu, pf, pnl); low = np.where(fu, lf, low)
        breach = live & (P + low <= floor)
        end[breach & ev] = 1
        end[breach & fu] = 2
        phase[breach] = 2
        ok = live & ~breach
        P = np.where(ok, P + pnl, P)
        peak = np.where(ok, np.maximum(peak, P), peak)
        lock = np.where(ev, LUCID.eval_lock, LUCID.funded_lock)
        floor = np.where(ok & ~fixed, np.minimum(peak - LUCID.dd, lock), floor)
        # evaluation pass
        traded = ok & (pnl != 0)
        best = np.where(ok & ev & traded, np.maximum(best, pnl), best)
        passed = ok & ev & (P >= LUCID.target) & (best <= LUCID.eval_consistency * P)
        if passed.any():
            pass_day[passed] = t
            phase[passed] = 3                        # transition marker, funded from tomorrow
            start_funded |= passed
        # funded bookkeeping and payouts
        f_ok = ok & fu
        cyc_p = np.where(f_ok, cyc_p + pnl, cyc_p)
        cyc_win = np.where(f_ok & (pnl >= LUCID.win_day), cyc_win + 1, cyc_win)
        elig = f_ok & (cyc_win >= LUCID.win_days) & (P > 0) & (cyc_p > 0)
        if elig.any():
            mx = np.minimum(LUCID.payout_frac * P, LUCID.payout_caps[0])
            if cfg.keep > 0:
                mx = np.minimum(mx, P - LUCID.floor_after_payout - cfg.keep)
            pay = elig & (mx >= LUCID.payout_min)
            if pay.any():
                amt = np.where(pay, mx, 0.0)
                gross += amt
                net += np.where(pay, amt * LUCID.split - ps.TRANSFER_FEE, 0.0)
                newf = pay & (first_pay < 0)
                first_acc = np.where(newf, accounts, first_acc)
                cash_first = np.where(newf, fees, cash_first)
                first_amt = np.where(newf, amt, first_amt)
                first_pay = np.where(newf, t, first_pay)
                P = P - amt
                npay = npay + pay
                npay_acc = npay_acc + pay
                cyc_win = np.where(pay, 0, cyc_win); cyc_p = np.where(pay, 0.0, cyc_p)
                fixed |= pay
                floor = np.where(pay, LUCID.floor_after_payout, floor)
                done = pay & (npay_acc >= LUCID.max_payouts)
                end[done] = 3
                phase[done] = 2
        phase[phase == 3] = 0                        # still "eval" until tomorrow's switch
        phase[start_funded] = 0
        best = np.where(start_funded, 0.0, best)
    for k in snapshots:
        snap.setdefault(k, net - fees)
    phase[start_funded] = 1
    return {"snap": snap, "passed": pass_day >= 0, "pass_day": pass_day, "first_pay": first_pay, "npay": npay,
            "gross": gross, "net": net, "end": end, "open_profit": np.where(phase == 1, P, 0.0),
            "accounts": accounts, "fees": fees, "cash_min": cash_min, "cash": net - fees,
            "first_acc": first_acc, "cash_first": cash_first, "first_amt": first_amt}


def metrics(res: dict, fee: float = LUCID.eval_fee) -> dict:
    p = res["passed"]
    fp = res["first_pay"]
    netc = res["net"] - fee
    return {"pass": float(p.mean()), "days_to_pass_med": float(np.median(res["pass_day"][p] + 1)) if p.any() else float("nan"),
            "payout_6m": float(((fp >= 0) & (fp < 126)).mean()), "payout_12m": float(((fp >= 0) & (fp < 252)).mean()),
            "payout_any": float((fp >= 0).mean()),
            "days_to_first_payout_med": float(np.median(fp[fp >= 0] + 1)) if (fp >= 0).any() else float("nan"),
            "payouts_mean": float(res["npay"].mean()), "net_mean": float(netc.mean()),
            "net_median": float(np.median(netc)), "p_profit": float((netc > 0).mean()),
            "blown_after_pass": float((res["end"][p] == 2).mean()) if p.any() else float("nan"),
            "moved_live": float((res["end"] == 3).mean())}
