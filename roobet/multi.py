"""Multi-outcome games (plinko tables, roulette, wheel, blackjack regimes): strategies,
Monte Carlo and exact Markov evaluation for strategies whose bet depends only on the bankroll.

A bet is (name, nets, probs, max_loss): the bankroll moves B -> B + floor(stake * net_k).
Same common rules as engine.py: whole-cent stakes, >= 1 cent, the bet's worst case must be
affordable (stake * max_loss <= B), challenge ends at >= $100 or 0.
"""
from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve

from engine import EPS, LEVELS, summarize
from games import START, TARGET


class Bets:
    def __init__(self, bets):
        self.names = [b[0] for b in bets]
        K = max(len(b[1]) for b in bets)
        self.nets = np.zeros((len(bets), K))
        self.cum = np.ones((len(bets), K))
        self.maxloss = np.array([b[3] for b in bets], float)
        self.k = np.array([len(b[1]) for b in bets])
        for j, (_, nets, probs, _) in enumerate(bets):
            nets, probs = np.asarray(nets, float), np.asarray(probs, float)
            self.nets[j, : len(nets)] = nets
            self.cum[j, : len(probs)] = np.cumsum(probs)
            self.cum[j, len(probs) - 1:] = 1.0
        self.raw = bets


# ------------------------------------------------------------------ strategies (stake, bet index)
class AllInEach:
    """Stake the whole bankroll (or what the max win needs) on bet j every time."""

    def __init__(self, j, name, top_net=None):
        self.j, self.name, self.top = j, name, top_net

    def act(self, B):
        s = B.copy()
        if self.top is not None:
            s = np.minimum(s, np.ceil((TARGET - B) / self.top - EPS).astype(np.int64))
        return np.maximum(s, 1), np.full(len(B), self.j)


class FlatEach:
    def __init__(self, stake, j, name):
        self.s, self.j, self.name = stake, j, name

    def act(self, B):
        return np.full(len(B), self.s), np.full(len(B), self.j)


class BlackjackBold:
    """Even-money bold play in blackjack: stake = min(B / reserve, T - B); the round is played
    with doubles/splits only if the bankroll covers them (regime chosen from the stake)."""

    def __init__(self, reserve, regimes_idx, name):
        self.reserve, self.idx, self.name = reserve, regimes_idx, name   # idx: dict regime -> bet j

    def act(self, B):
        s = np.minimum(B // self.reserve, TARGET - B)
        s = np.maximum(s, 1)
        j = np.where(4 * s <= B, self.idx["full"], np.where(2 * s <= B, self.idx["double"], self.idx["none"]))
        return s, j


class GridPolicy:
    """A DP policy computed on a grid of `unit` cents: stake (in units) and bet index per grid state."""

    def __init__(self, unit, bet_of, stake_of, name):
        self.unit, self.bet_of, self.stake_of, self.name = unit, bet_of, stake_of, name

    def act(self, B):
        i = np.minimum(B // self.unit, len(self.bet_of) - 1)
        return np.maximum(self.stake_of[i] * self.unit, 1), self.bet_of[i]


def _clamp(strategy, bets, B):
    s, j = strategy.act(B)
    s = np.minimum(s, (B / bets.maxloss[j]).astype(np.int64))
    return np.maximum(s, 1), j


def simulate_multi(strategy, bets: Bets, n=100_000, seed=0, cap=100_000):
    rng = np.random.default_rng(seed)
    ids = np.arange(n)
    B = np.full(n, START, np.int64)
    bets_n = np.zeros(n, np.int64)
    wag = np.zeros(n, np.int64)
    peak = B.copy()
    maxdd = np.zeros(n, np.int64)
    out = {k: np.zeros(n, np.int64) for k in ("B", "bets", "wagered", "peak", "maxdd")}
    out["end"] = np.zeros(n, np.int8)
    while len(ids):
        s, j = _clamp(strategy, bets, B)
        u = rng.random(len(ids))
        k = (u[:, None] > bets.cum[j]).sum(axis=1)
        B = B + np.floor(s * bets.nets[j, k] + EPS).astype(np.int64)
        B = np.maximum(B, 0)
        bets_n += 1
        wag += s
        peak = np.maximum(peak, B)
        maxdd = np.maximum(maxdd, peak - B)
        end = np.zeros(len(ids), np.int8)
        end[B >= TARGET] = 1
        end[(end == 0) & (B < 1)] = 2
        end[(end == 0) & (bets_n >= cap)] = 4
        done = end > 0
        if done.any():
            d = ids[done]
            for key, arr in (("B", B), ("bets", bets_n), ("wagered", wag), ("peak", peak), ("maxdd", maxdd)):
                out[key][d] = arr[done]
            out["end"][d] = end[done]
            keep = ~done
            ids, B, bets_n, wag, peak, maxdd = ids[keep], B[keep], bets_n[keep], wag[keep], peak[keep], maxdd[keep]
    return out, summarize(out)


def markov_stateless(strategy, bets: Bets, levels=LEVELS):
    """Exact evaluation over all cent bankrolls 1..9,999 for a bankroll-only strategy."""
    N = TARGET
    B = np.arange(1, N)
    s, j = _clamp(strategy, bets, B)
    rows, cols, vals = [], [], []
    rT = np.zeros(N - 1)
    rF = np.zeros(N - 1)
    for k in range(bets.nets.shape[1]):
        pk = np.diff(np.concatenate([np.zeros((len(bets.cum), 1)), bets.cum], axis=1), axis=1)[j, k]
        nxt = B + np.floor(s * bets.nets[j, k] + EPS).astype(np.int64)
        nxt = np.maximum(nxt, 0)
        m = pk > 0
        win = m & (nxt >= N)
        rT += np.where(win, pk, 0.0)
        rF += np.where(win, pk * nxt / 100, 0.0)
        tr = m & (nxt >= 1) & (nxt < N)
        rows.append(B[tr] - 1)
        cols.append(nxt[tr] - 1)
        vals.append(pk[tr])
    Q = sparse.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(N - 1, N - 1))
    A = (sparse.identity(N - 1, format="csr") - Q).tocsc()
    sol = spsolve(A, np.column_stack([rT, rF, np.ones(N - 1), s / 100]))
    i0 = START - 1
    res = dict(p_target=sol[i0, 0], mean_final=sol[i0, 1], mean_bets=sol[i0, 2], mean_wagered=sol[i0, 3])
    res["p_ruin"] = 1 - res["p_target"]
    reach = {}
    for L in levels:
        if L >= TARGET:
            reach[str(L // 100)] = res["p_target"]
            continue
        keep = B < L
        Qk = Q[keep][:, keep]
        r = np.asarray(Q[keep][:, ~keep].sum(axis=1)).ravel() + rT[keep]
        x = spsolve((sparse.identity(int(keep.sum()), format="csr") - Qk).tocsc(), r)
        reach[str(L // 100)] = float(x[i0])
    res["reach"] = reach
    return res


def dp_grid(bets: Bets, unit=25, iters=2000, tol=1e-12):
    """Optimal stationary policy on a grid of `unit` cents (value iteration, conservative floors)."""
    n = TARGET // unit
    V = np.zeros(n + 1)
    V[n] = 1.0
    i = np.arange(n + 1)
    S = np.arange(1, n + 1)
    nexts, masks = [], []
    for j in range(len(bets.raw)):
        _, nets, probs, maxloss = bets.raw[j]
        nets = np.asarray(nets, float)
        nx = i[:, None, None] + np.floor(S[None, :, None] * nets[None, None, :] + EPS).astype(np.int64)
        nexts.append((np.clip(nx, 0, n), np.asarray(probs, float)))
        masks.append(S[None, :] * maxloss <= i[:, None])
    bet_of = np.zeros(n + 1, np.int64)
    stake_of = np.zeros(n + 1, np.int64)
    for it in range(iters):
        best = np.full(n + 1, -1.0)
        for j, ((nx, p), mk) in enumerate(zip(nexts, masks)):
            q = (V[nx] * p).sum(axis=2)
            q = np.where(mk, q, -1.0)
            k = q.argmax(axis=1)
            v = q[i, k]
            better = v > best + 1e-15
            best = np.where(better, v, best)
            bet_of = np.where(better, j, bet_of)
            stake_of = np.where(better, S[k], stake_of)
        best[0], best[n] = 0.0, 1.0
        diff = np.max(np.abs(best - V))
        V = best
        if diff < tol:
            break
    return V, bet_of, stake_of, it + 1
