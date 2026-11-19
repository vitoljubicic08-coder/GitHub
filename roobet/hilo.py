"""HiLo: the best single-round plan for turning a stake into >= $100.

Rules from Roobet's HiLo verifier (2026-10-12):
  * every card's rank is uniform on A..K (52-bit hash mod 13, independent draws);
  * on an Ace you may call 'higher' (12/13) or 'same' (1/13); on a King 'lower' (12/13) or
    'same' (1/13); on 2..Q 'higher or same' ((14-u)/13) or 'lower or same' (u/13);
  * a correct call multiplies the running multiplier by 1/p exactly; a wrong call loses;
  * 'skip' draws a new card at no cost (at most 50 skips per round);
  * the payout is stake x 0.99 x (product of the step multipliers): a flat 1% house edge.
Because each step is exactly fair, P(cash out at M) = 1/M for any plan that stops at M, so
with all $10 staked P(success) = 1 / (smallest reachable M >= 10/0.99) — the game rewards
plans that overshoot the 10.101x threshold as little as possible.
"""
from __future__ import annotations

from itertools import combinations_with_replacement
from math import prod, log, floor

import numpy as np

RANKS = 13
EDGE = 0.01
MAX_SKIPS = 50


def actions(u: int):
    """(j, winning ranks) for each call allowed on upcard u (1=A .. 13=K); multiplier 13/j."""
    if u == 1:
        return [(12, range(2, 14)), (1, range(1, 2))]
    if u == 13:
        return [(12, range(1, 13)), (1, range(13, 14))]
    return [(14 - u, range(u, 14)), (u, range(1, u + 1))]


J_TABLE = np.zeros((RANKS + 1, 3), np.int64)          # J_TABLE[u, call] = winning ranks j
for _u in range(1, RANKS + 1):
    for _c, (_j, _w) in enumerate(actions(_u), start=1):
        J_TABLE[_u, _c] = _j


def m_star(stake=10.0, target=100.0, kept=0.0):
    return (target - kept) / (stake * (1 - EDGE))


def best_plan(mstar: float, max_steps: int = 7):
    """Unlimited skips: the multiset of j's whose product 13^n/prod(j) >= mstar is smallest."""
    best = (np.inf, None)
    for n in range(1, max_steps + 1):
        for js in combinations_with_replacement(range(1, 13), n):
            M = RANKS ** n / prod(js)
            if mstar <= M < best[0]:
                best = (M, js)
    return best


class FiniteSkipDP:
    """Exact-in-rules DP on a log grid of the running multiplier, with the 50-skip budget.

    Increments ln(13/j) are rounded DOWN to the grid, so the value is a (tight) lower bound.
    V[i, u, k] = success probability at multiplier bin i, upcard u, k skips left.
    """

    def __init__(self, mstar: float, delta: float = 1e-4, skips: int = MAX_SKIPS):
        self.mstar, self.delta, self.K = mstar, delta, skips
        self.nb = int(np.ceil(log(mstar) / delta))           # bin index >= nb means success
        self.inc = {j: int(floor(log(RANKS / j) / delta)) for j in range(1, 13)}
        nb, K = self.nb, skips
        V = np.zeros((nb, RANKS + 1, K + 1))                  # upcard index 1..13
        pol = np.zeros((nb, RANKS + 1, K + 1), np.int8)       # 0 skip, 1 first call, 2 second call
        block = min(self.inc.values())
        for hi in range(nb, 0, -block):
            lo = max(0, hi - block)
            bins = np.arange(lo, hi)
            for k in range(K + 1):
                for u in range(1, RANKS + 1):
                    vals = []
                    for (j, win) in actions(u):
                        tgt = bins + self.inc[j]
                        succ = tgt >= nb
                        tg = np.minimum(tgt, nb - 1)
                        w = np.zeros(len(bins))
                        for r in win:
                            w += np.where(succ, 1.0, V[tg, r, k])
                        vals.append(w / RANKS)
                    best = np.maximum(vals[0], vals[1])
                    choice = np.where(vals[0] >= vals[1], 1, 2)
                    if k > 0:
                        skip = V[bins, 1:, k - 1].mean(axis=1)
                        choice = np.where(skip > best + 1e-15, 0, choice)
                        best = np.maximum(best, skip)
                    V[bins, u, k] = best
                    pol[bins, u, k] = choice
        self.V, self.pol = V, pol

    def p_success(self) -> float:
        return float(self.V[0, 1:, self.K].mean())

    def simulate(self, n=100_000, seed=0):
        """Play the DP policy with true (unrounded) multipliers; returns success flags and steps."""
        rng = np.random.default_rng(seed)
        logM = np.zeros(n)
        u = rng.integers(1, RANKS + 1, n)
        k = np.full(n, self.K)
        alive = np.ones(n, bool)
        won = np.zeros(n, bool)
        steps = np.zeros(n, np.int64)
        lm_star = log(self.mstar)
        while alive.any():
            a = np.where(alive)[0]
            b = np.minimum((logM[a] / self.delta).astype(np.int64), self.nb - 1)
            c = self.pol[b, u[a], k[a]]
            r = rng.integers(1, RANKS + 1, len(a))
            sk = c == 0
            k[a[sk]] -= 1
            u[a[sk]] = r[sk]
            pl = ~sk
            ia = a[pl]
            uu, cc, rr = u[ia], c[pl], r[pl]
            j = J_TABLE[uu, cc]
            ok = np.where(cc == 1, np.where(uu == 13, rr <= 12, np.where(uu == 1, rr >= 2, rr >= uu)),
                          np.where(uu == 1, rr == 1, np.where(uu == 13, rr == 13, rr <= uu)))
            steps[ia] += 1
            logM[ia] += np.log(RANKS / j)
            u[ia] = rr
            lost = ia[~ok]
            alive[lost] = False
            done = ia[ok & (logM[ia] >= lm_star - 1e-12)]
            won[done] = True
            alive[done] = False
        return won, steps
