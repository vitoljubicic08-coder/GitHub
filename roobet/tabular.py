"""Bankroll-only policies as explicit transition tables: exact evaluation and fast simulation.

A table gives, for every bankroll B = 1..9,999 cents, up to K outcomes (probability, next
bankroll) and the stake placed. Any policy that looks only at the current bankroll fits:
DP policies over one game or many, multi-outcome games (Plinko, blackjack, baccarat),
and hand-built mixtures (e.g. blackjack until $50, then one Dice bet). Evaluation is one
sparse linear solve; simulation samples the same table.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve

from engine import EPS, LEVELS20, summarize
from games import TARGET


@dataclass
class Table:
    probs: np.ndarray          # (K, TARGET) outcome probabilities per bankroll (column 0 unused)
    nxt: np.ndarray            # (K, TARGET) next bankroll in cents (>= TARGET means success)
    stake: np.ndarray          # (TARGET,) stake in cents
    name: str = ""
    family: str = ""
    game: np.ndarray | None = None     # (TARGET,) index of the game/bet used, for reporting


def two_outcome(game, stake_fn, name, family="table"):
    """Each bet is aimed at $100: stake s = stake_fn(B) at multiplier (T - B + s)/s."""
    B = np.arange(TARGET)
    s = np.clip(np.asarray(stake_fn(B), np.int64), 1, np.maximum(B, 1))
    m_req = (TARGET - B + s) / s
    if hasattr(game, "choose"):
        m, p, g = game.choose(m_req)
    else:
        (m, p), g = game.quote(m_req), np.zeros(TARGET, np.int64)
    win = B - s + np.floor(s * m + EPS).astype(np.int64)
    probs = np.vstack([p, 1 - p])
    nxt = np.vstack([win, B - s])
    return Table(probs, nxt, s, name, family, g)


def from_bets(bets, act, name, family="table"):
    """Multi-outcome bets (multi.Bets) chosen by act(B) -> (stake, bet index)."""
    B = np.arange(TARGET)
    s, j = act(np.maximum(B, 1))
    s = np.asarray(s, np.int64)
    j = np.asarray(j, np.int64)
    s = np.minimum(s, (np.maximum(B, 1) / bets.maxloss[j]).astype(np.int64))
    s = np.maximum(s, 1)
    K = bets.nets.shape[1]
    pk = np.diff(np.concatenate([np.zeros((len(bets.cum), 1)), bets.cum], axis=1), axis=1)
    probs = pk[j].T                                             # (K, TARGET)
    nxt = (B[None, :] + np.floor(s[None, :] * bets.nets[j].T + EPS)).astype(np.int64)
    nxt = np.maximum(nxt, 0)
    return Table(probs, nxt, s, name, family, j)


def mix(tables, chooser, name, family="mixed"):
    """Use tables[chooser(B)] at each bankroll (chooser returns an index array)."""
    B = np.arange(TARGET)
    k = np.asarray(chooser(B), np.int64)
    K = max(t.probs.shape[0] for t in tables)
    probs = np.zeros((K, TARGET))
    nxt = np.zeros((K, TARGET), np.int64)
    stake = np.zeros(TARGET, np.int64)
    game = np.zeros(TARGET, np.int64)
    for i, t in enumerate(tables):
        sel = k == i
        kk = t.probs.shape[0]
        probs[:kk, sel] = t.probs[:, sel]
        nxt[:kk, sel] = t.nxt[:, sel]
        stake[sel] = t.stake[sel]
        game[sel] = i
    return Table(probs, nxt, stake, name, family, game)


def evaluate(tab: Table, start=2000, levels=LEVELS20):
    """Exact P($100), P(ruin), E[final], SD[final], E[bets], E[wagered], P(touch L)."""
    N = TARGET
    B = np.arange(N)
    rows, cols, vals = [], [], []
    rT = np.zeros(N)
    rF = np.zeros(N)
    rF2 = np.zeros(N)
    for k in range(tab.probs.shape[0]):
        p = tab.probs[k].copy()
        p[0] = 0.0
        nx = tab.nxt[k]
        win = (p > 0) & (nx >= N)
        rT += np.where(win, p, 0.0)
        rF += np.where(win, p * nx / 100, 0.0)
        rF2 += np.where(win, p * (nx / 100) ** 2, 0.0)
        tr = (p > 0) & (nx >= 1) & (nx < N) & (B >= 1)
        rows.append(B[tr])
        cols.append(nx[tr])
        vals.append(p[tr])
    Q = sparse.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(N, N))
    keep = np.arange(1, N)
    Qk = Q[keep][:, keep]
    A = (sparse.identity(N - 1, format="csr") - Qk).tocsc()
    rhs = np.column_stack([rT[keep], rF[keep], rF2[keep], np.ones(N - 1), tab.stake[keep] / 100])
    sol = spsolve(A, rhs)
    i0 = start - 1
    res = dict(p_target=float(sol[i0, 0]), mean_final=float(sol[i0, 1]),
               sd_final=float(np.sqrt(max(sol[i0, 2] - sol[i0, 1] ** 2, 0.0))),
               mean_bets=float(sol[i0, 3]), mean_wagered=float(sol[i0, 4]))
    res["p_ruin"] = 1 - res["p_target"]
    res["V"] = sol[:, 0]                  # P($100) from every bankroll 1..9,999 (index B-1)
    reach = {}
    for L in levels:
        if start >= L:
            reach[str(L // 100)] = 1.0
            continue
        sub = (keep < L)
        Qs = Q[keep[sub]][:, keep[sub]]
        r = np.zeros(int(sub.sum()))
        for k in range(tab.probs.shape[0]):
            p = tab.probs[k][keep[sub]]
            r += np.where(tab.nxt[k][keep[sub]] >= L, p, 0.0)
        x = spsolve((sparse.identity(int(sub.sum()), format="csr") - Qs).tocsc(), r)
        reach[str(L // 100)] = float(x[i0])
    res["reach"] = reach
    return res


def simulate(tab: Table, n=1_000_000, seed=0, start=2000, levels=LEVELS20, cap=1_000_000, chunk=250_000):
    """Monte Carlo of the same table (same per-path records as engine.simulate)."""
    cum = np.cumsum(tab.probs, axis=0)
    cum[-1] = 1.0 + 1e-12
    sizes = [chunk] * (n // chunk) + ([n % chunk] if n % chunk else [])
    kids = np.random.SeedSequence(seed).spawn(len(sizes))
    parts = []
    for size, kid in zip(sizes, kids):
        rng = np.random.default_rng(kid)
        ids = np.arange(size)
        B = np.full(size, start, np.int64)
        bets = np.zeros(size, np.int64)
        wins = np.zeros(size, np.int64)
        wag = np.zeros(size, np.int64)
        peak = B.copy()
        maxdd = np.zeros(size, np.int64)
        maxddp = np.zeros(size)
        out = {k: np.zeros(size, np.int64) for k in ("B", "bets", "wins", "wagered", "peak", "maxdd")}
        out["maxdd_pct"] = np.zeros(size)
        out["end"] = np.zeros(size, np.int8)
        while len(ids):
            u = rng.random(len(ids))
            k = (u[:, None] > cum[:, B].T).sum(axis=1)
            nb = tab.nxt[k, B]
            wins += nb > B
            wag += tab.stake[B]
            B = np.maximum(nb, 0)
            bets += 1
            peak = np.maximum(peak, B)
            maxdd = np.maximum(maxdd, peak - B)
            maxddp = np.maximum(maxddp, (peak - B) / peak)
            end = np.zeros(len(ids), np.int8)
            end[B >= TARGET] = 1
            end[(end == 0) & (B < 1)] = 2
            end[(end == 0) & (bets >= cap)] = 4
            done = end > 0
            if done.any():
                d = ids[done]
                for key, arr in (("B", B), ("bets", bets), ("wins", wins), ("wagered", wag), ("peak", peak),
                                 ("maxdd", maxdd), ("maxdd_pct", maxddp)):
                    out[key][d] = arr[done]
                out["end"][d] = end[done]
                keep = ~done
                ids, B, bets, wins, wag = ids[keep], B[keep], bets[keep], wins[keep], wag[keep]
                peak, maxdd, maxddp = peak[keep], maxdd[keep], maxddp[keep]
        parts.append(out)
    paths = {key: np.concatenate([q[key] for q in parts]) for key in parts[0]}
    return paths, summarize(paths, start, levels)
