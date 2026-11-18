"""Grid search over implementable pies (5% steps) on simulated 24-month paths, for objectives A-D.

Lump sum EUR 5,000, rebalanced once at month 12. Terminal value = 5000 * (1 - costs) * (G1 @ w) * (G2 @ w),
where G1, G2 are each sleeve's gross return over months 1-12 and 13-24 on the same simulated path.
"""
from __future__ import annotations

import itertools

import numpy as np

from sim import trade_cost

GRID_SLEEVES = ["WORLD", "NDX", "SEMI", "NVDA", "SCV", "EM", "GOLD", "CASH"]
CAPS = {"WORLD": 1.0, "NDX": 0.6, "SEMI": 0.4, "NVDA": 0.15, "SCV": 0.2, "EM": 0.2, "GOLD": 0.25, "CASH": 0.5}


def grid(step=0.05):
    n = round(1 / step)
    caps = [round(CAPS[s] / step) for s in GRID_SLEEVES]
    out = []

    def rec(i, left, cur):
        if i == len(GRID_SLEEVES) - 1:
            if left <= caps[i]:
                out.append(cur + [left])
            return
        for k in range(min(left, caps[i]) + 1):
            rec(i + 1, left - k, cur + [k])
    rec(0, n, [])
    return np.array(out, dtype=float) * step


def terminal(R: np.ndarray, cols, W: np.ndarray, initial=5000.0):
    j = [cols.index(s) for s in GRID_SLEEVES]
    G1 = np.exp(R[:, :12, j].sum(1))                                  # (paths, sleeves)
    G2 = np.exp(R[:, 12:24, j].sum(1))
    tc = np.array([trade_cost(s) for s in GRID_SLEEVES])
    return initial * (1 - W @ tc)[:, None] * (W @ G1.T) * (W @ G2.T)


def stats(F: np.ndarray, initial=5000.0) -> dict:
    return {"mean": F.mean(1), "median": np.median(F, 1), "p5": np.percentile(F, 5, axis=1),
            "p_double": (F >= 2 * initial).mean(1), "p_loss20": (F <= 0.8 * initial).mean(1),
            "p_loss40": (F <= 0.6 * initial).mean(1), "p_ge7500": (F >= 7500).mean(1)}


def grid_stats(R: np.ndarray, cols, W: np.ndarray, chunk=500) -> dict:
    """Statistics for every pie in W, computed chunk by chunk to bound memory."""
    parts = [stats(terminal(R, cols, W[a:a + chunk])) for a in range(0, len(W), chunk)]
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def pick(st: dict, W: np.ndarray, objective: str, loss20_max=0.10, loss40_max=0.015):
    ok = np.ones(len(W), bool)
    if objective == "A":
        score = st["mean"]
    elif objective == "B":
        score = st["p_double"] + 1e-9 * st["mean"]
    elif objective == "C":
        ok = (st["p_loss20"] <= loss20_max) & (st["p_loss40"] <= loss40_max)
        score = st["mean"]
    else:
        raise ValueError(objective)
    s = np.where(ok, score, -np.inf)
    i = int(np.argmax(s))
    return i, {k: float(v[i]) for k, v in st.items()}, dict(zip(GRID_SLEEVES, map(float, W[i])))


def label(w: dict) -> str:
    return ", ".join(f"{k} {v * 100:.0f}%" for k, v in w.items() if v > 0)
