"""Exact results: the upper bound, closed forms, and dynamic programming over the bankroll.

Notation: b = bankroll, T = target ($100), r = RTP of the best available bet, e = 1 - r.

1. Upper bound (any strategy, any sequence of bets whose RTP is at most r):
   each bet's expected net is -e * stake, so E[final] = b - e * E[W] (W = total wagered).
   On failure the whole bankroll has been lost, so W >= b - 0.01 there; on success the final
   bankroll is >= T. Hence T*P <= b - e*(b - 0.01)*(1 - P), i.e.
        P <= (b - e*b') / (T - e*b'),   b' = b - 0.01.
2. One all-in bet at multiplier T/b: P = r * b / T  (9.90% at r = 0.99).
3. k equal all-in stages at m = (T/b)^(1/k): P = r^k * b / T  (fewer stages is better).
4. Stake ds at the multiplier that lands exactly on T, repeatedly (the continuous limit):
        dV/db = r (1 - V)/(T - b)  =>  V(b) = 1 - (1 - b/T)^r   (9.904% at r = 0.99).
5. Flat even-money bets with win probability p (gambler's ruin):
        P = (1 - (q/p)^i) / (1 - (q/p)^N).
"""
from __future__ import annotations

import numpy as np

from games import START, TARGET

EPS = 1e-9


def upper_bound(e, b=START, T=TARGET):
    bp = b - 1
    return (b - e * bp) / (T - e * bp)


def single_bet(r, b=START, T=TARGET):
    return r * b / T


def k_stage(r, k, b=START, T=TARGET):
    return r ** k * b / T


def timid_limit(r, b=START, T=TARGET):
    return 1 - (1 - b / T) ** r


def gamblers_ruin(p, i, N):
    q = 1 - p
    if abs(p - q) < 1e-15:
        return i / N
    x = q / p
    return (1 - x ** i) / (1 - x ** N)


# --------------------------------------------------------------------------- cent-exact DP
def dp_target_hit(game, b_max=TARGET - 1):
    """Optimal policy among strategies whose every bet would land on >= $100 if it wins.

    V(b) = max_s  p(s,b) + (1 - p(s,b)) V(b - s),  p(s,b) = P(win) of the cheapest quote with
    floor(s*m) >= T - b + s. Exact on the whole-cent grid (forward recursion, no iteration).
    """
    V = np.zeros(b_max + 1)
    pol = np.zeros(b_max + 1, np.int64)
    for b in range(1, b_max + 1):
        s = np.arange(1, b + 1)
        m_req = (TARGET - b + s) / s
        m, p = game.quote(m_req)
        ok = (m >= m_req - EPS) & (b - s + np.floor(s * m + EPS) >= TARGET)
        val = np.where(ok, p + (1 - p) * V[b - s], -1.0)
        j = int(np.argmax(val))
        if val[j] < 0:                 # no bet from b can reach $100 (only b = 1 cent on Dice)
            V[b], pol[b] = 0.0, b
        else:
            V[b], pol[b] = val[j], s[j]
    return V, pol


def dp_continuous(r, unit=50, allow_intermediate=True, iters=400, tol=1e-13):
    """Coarse-grid DP in a casino that offers every multiplier at RTP r (no grid limits).

    From b, stake s and aim at any landing point b' in (b, T]: p = r*s/(b' - b + s).
    With allow_intermediate=False only b' = T is allowed. Value iteration from below.
    Used to show that aiming every bet at the target is optimal (bold in odds).
    """
    n = TARGET // unit
    b = np.arange(n + 1)
    V = np.zeros(n + 1)
    V[n] = 1.0
    S, Bp = np.meshgrid(np.arange(1, n + 1), np.arange(1, n + 1), indexing="ij")    # stake, landing
    pol = np.zeros(n + 1, np.int64)
    for _ in range(iters):
        Vn = V.copy()
        for i in range(1, n):
            s = S[: i, :]                      # stakes 1..i
            bp = Bp[: i, :]
            valid = bp > i
            if not allow_intermediate:
                valid &= bp == n
            p = np.where(valid, r * s / np.maximum(bp - i + s, 1), 0.0)
            val = np.where(valid, p * V[np.minimum(bp, n)] + (1 - p) * V[i - s], -1.0)
            k = int(np.argmax(val))
            Vn[i] = val.flat[k]
            pol[i] = s.flat[k]
        if np.max(np.abs(Vn - V)) < tol:
            V = Vn
            break
        V = Vn
    return V, pol


def dp_multi(bets, unit=10, stake_fracs=None, iters=3000, tol=1e-12, cap_needed=True):
    """Value iteration for multi-outcome bets on a grid of `unit` cents.

    bets: list of (name, nets array, probs array, max_loss multiple) — e.g. plinko tables,
    roulette options, blackjack regimes (a regime with max loss 4 needs stake <= B/4).
    Landing points are floored to the grid (conservative). Returns V, policy (bet, stake).
    """
    n = TARGET // unit
    V = np.zeros(n + 1)
    V[n] = 1.0
    best_bet = np.zeros(n + 1, np.int64)
    best_stake = np.zeros(n + 1, np.int64)
    # precompute transitions per bet: next[i, s, k]
    trans = []
    for name, nets, probs, maxloss in bets:
        nets = np.asarray(nets, float)
        probs = np.asarray(probs, float)
        trans.append((nets, probs, maxloss))
    for _ in range(iters):
        Vn = V.copy()
        for i in range(1, n):
            best = -1.0
            for j, (nets, probs, maxloss) in enumerate(trans):
                smax = int(i // maxloss)
                if smax < 1:
                    continue
                s = np.arange(1, smax + 1)
                nxt = i + np.floor(np.outer(s, nets) + EPS).astype(np.int64)
                nxt = np.clip(nxt, 0, n)
                val = (V[nxt] * probs).sum(axis=1)
                k = int(np.argmax(val))
                if val[k] > best + 1e-15:
                    best, best_bet[i], best_stake[i] = val[k], j, s[k]
            Vn[i] = best
        if np.max(np.abs(Vn - V)) < tol:
            V = Vn
            break
        V = Vn
    return V, best_bet, best_stake


# --------------------------------------------------------------------------- Phase 3: optimality checks
def value_array(V):
    """Append V(>= $100) = 1 so that next-bankroll indices up to TARGET can be looked up."""
    out = np.ones(TARGET + 1)
    out[: len(V)] = V
    out[0] = 0.0
    return out


def max_improvement(V, nets, probs, maxloss=1.0, b_lo=1, b_hi=TARGET - 1, chunk=64):
    """Largest one-step gain of a multi-outcome bet over V, across all bankrolls and stakes.

    For every bankroll b and stake s (s * maxloss <= b), Q = sum_k p_k V(b + floor(s*net_k)).
    If Q <= V(b) everywhere (gain <= 0), adding this bet cannot raise the optimum: V is then
    an excessive function for the enlarged game, which bounds every strategy's success
    probability (supermartingale argument). Returns (max gain, b, s) of the best violation.
    """
    Vx = value_array(V)
    nets = np.asarray(nets, float)
    probs = np.asarray(probs, float)
    best = (-np.inf, 0, 0)
    for lo in range(b_lo, b_hi + 1, chunk):
        b = np.arange(lo, min(lo + chunk, b_hi + 1))
        smax = int(b[-1] // maxloss)
        if smax < 1:
            continue
        s = np.arange(1, smax + 1)
        nx = b[:, None, None] + np.floor(s[None, :, None] * nets[None, None, :] + EPS).astype(np.int64)
        nx = np.clip(nx, 0, TARGET)
        q = (Vx[nx] * probs).sum(axis=2)
        q = np.where(s[None, :] * maxloss <= b[:, None], q, -1.0)
        gain = q - Vx[b][:, None]
        i, j = np.unravel_index(np.argmax(gain), gain.shape)
        if gain[i, j] > best[0]:
            best = (float(gain[i, j]), int(b[i]), int(s[j]))
    return best


def sampled_two_outcome_check(V, game, n=20_000_000, seed=0, chunk=2_000_000, b_lo=1):
    """Random (bankroll, stake, multiplier) triples, including bets that land BELOW $100:
    the largest gain of p V(win) + (1-p) V(loss) over V(b). Evidence (not proof) that
    aiming every bet at $100 cannot be beaten by intermediate landing points."""
    Vx = value_array(V)
    rng = np.random.default_rng(seed)
    best = (-np.inf, 0, 0, 0.0)
    for _ in range(n // chunk):
        b = rng.integers(b_lo, TARGET, chunk)
        s = np.maximum((rng.random(chunk) ** 2 * b).astype(np.int64), 1)
        m_req = np.exp(rng.uniform(np.log(1.0103), np.log(TARGET / 1.0), chunk))
        m, p = game.quote(m_req)
        win = np.minimum(b - s + np.floor(s * m + EPS).astype(np.int64), TARGET)
        q = p * Vx[win] + (1 - p) * Vx[b - s]
        gain = q - Vx[b]
        k = int(np.argmax(gain))
        if gain[k] > best[0]:
            best = (float(gain[k]), int(b[k]), int(s[k]), float(m[k]))
    return best


def target_hit_stats(game, pol):
    """For the target-hitting policy `pol` (stake per bankroll): exact P, E[final], E[wagered],
    E[bets] from every bankroll, by forward recursion (a loss always moves down)."""
    N = len(pol)
    P = np.zeros(N)
    F = np.zeros(N)
    W = np.zeros(N)
    K = np.zeros(N)
    for b in range(1, N):
        s = int(pol[b])
        m_req = (TARGET - b + s) / s
        m, p = game.quote(np.array([m_req]))
        m, p = float(m[0]), float(p[0])
        win = b - s + np.floor(s * m + EPS)
        if win < TARGET:               # this bet cannot reach $100 (1-cent bankroll on Dice)
            p = 0.0
        P[b] = p + (1 - p) * P[b - s]
        F[b] = p * win / 100 + (1 - p) * F[b - s]
        W[b] = s / 100 + (1 - p) * W[b - s]
        K[b] = 1 + (1 - p) * K[b - s]
    return P, F, W, K
