"""Challenge engine: two-outcome game quotes, betting strategies, Monte Carlo and exact Markov chains.

A challenge starts at $10.00 (1,000 cents) and ends when the bankroll reaches $100.00
(10,000 cents), when it falls below the $0.01 minimum stake (i.e. reaches 0 cents), when a
strategy's own stop rule fires (stop-loss / take-profit), or at the bet cap.

Identical rules for every strategy (so results are comparable):
  * stakes are whole cents, at least 1 cent and at most the bankroll;
  * a stake is never larger than needed to reach $100 on a win (the strategy's stake is
    cut to ceil(shortfall / (multiplier - 1)));
  * a win pays floor(stake * multiplier) cents in total (stake included);
  * every bet is independent (the verifiers show fresh hashes per bet / round).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve

from games import START, TARGET

EPS = 1e-9


# =========================================================================== game quotes
class Game:
    """A two-outcome game: quote(m_req) -> (m, p), the cheapest available multiplier >= m_req."""
    name = "game"
    rtp = 1.0
    max_mult = 1e6

    def quote(self, m_req: np.ndarray):
        raise NotImplementedError


class Dice(Game):
    """[V] roll grid 0.00-99.99; multiplier = 100*rtp/chance (chance 0.01-98.00%, 2 dp)."""

    def __init__(self, rtp: float = 0.99):
        self.rtp = rtp
        self.name = f"Dice (RTP {rtp*100:.1f}%)"
        self.max_mult = 100 * rtp / 0.01

    def quote(self, m_req):
        m_req = np.maximum(np.asarray(m_req, float), 100 * self.rtp / 98.0)
        c = np.floor(100.0 * self.rtp / m_req * 100 + EPS) / 100
        c = np.clip(c, 0.01, 98.0)
        return 100.0 * self.rtp / c, c / 100.0


class Limbo(Game):
    """[V] target t (2 dp, 1.01-1,000,000); P(win) = 0.98/t."""

    def __init__(self, rtp: float = 0.98, name="Limbo"):
        self.rtp, self.name = rtp, name

    def quote(self, m_req):
        t = np.ceil(np.asarray(m_req, float) * 100 - EPS) / 100
        t = np.clip(t, 1.01, 1e6)
        return t, self.rtp / t


class Crash(Game):
    """[V] auto-cashout t (2 dp, >= 1.01); P(crash >= t) = 0.96 * 99/(100t - 1)."""
    name = "Crash"
    rtp = 0.96 * 0.99          # RTP tends to 95.04% for large targets, 95.99% at 1.01x

    def quote(self, m_req):
        t = np.ceil(np.asarray(m_req, float) * 100 - EPS) / 100
        t = np.maximum(t, 1.01)
        return t, 0.96 * 99.0 / (100.0 * t - 1.0)


class Menu(Game):
    """A finite menu of (multiplier, probability) bets; quote picks the smallest m >= m_req."""

    def __init__(self, name, mults, probs):
        order = np.argsort(mults)
        self.name = name
        self.m = np.asarray(mults, float)[order]
        self.p = np.asarray(probs, float)[order]
        self.rtp = float(np.max(self.m * self.p))
        self.max_mult = float(self.m[-1])

    def quote(self, m_req):
        i = np.searchsorted(self.m, np.asarray(m_req, float) - EPS)
        i = np.minimum(i, len(self.m) - 1)
        return self.m[i], self.p[i]


def roulette_menu(bait_counts_as_colour=True):
    n = 7 if bait_counts_as_colour else 6
    return Menu("Roulette", [2.0, 7.0, 14.0], [n / 15, 2 / 15, 1 / 15])


def towers_menu():
    from games import TOWERS_SAFE
    ms, ps = [], []
    for q in TOWERS_SAFE.values():
        for n in range(1, 9):
            ms.append(round((0.96 / q) ** n, 2))
            ps.append(q ** n)
    return Menu("Towers", ms, ps)


def wheel_high_menu():
    return Menu("Wheel (high)", [10, 20, 30, 40, 50], [0.98 / n for n in (10, 20, 30, 40, 50)])


def coinflip_menu():
    return Menu("Coinflip", [1.92], [0.5])


def mines_menu(rtp=0.96, grid=25):
    from math import comb
    ms, ps = [], []
    for k in range(1, grid):
        for picks in range(1, grid - k + 1):
            p = comb(grid - k, picks) / comb(grid, picks)
            m = np.floor(rtp / p * 100) / 100
            if 1.01 <= m <= 1e6:
                ms.append(m)
                ps.append(p)
    return Menu(f"Mines (RTP {rtp*100:.0f}%, unverified)", ms, ps)


# =========================================================================== strategies
def _ceil_div(a, b):
    return -(-a // b)


def stake_needed(B, m):
    """Smallest whole-cent stake s with B - s + floor(s*m) >= TARGET."""
    short = TARGET - B
    s = np.ceil(short / (m - 1.0) - EPS).astype(np.int64)
    s = np.maximum(s, 1)
    bad = B - s + np.floor(s * m + EPS) < TARGET
    while np.any(bad):
        s = np.where(bad, s + 1, s)
        bad = B - s + np.floor(s * m + EPS) < TARGET
    return s


@dataclass
class Strategy:
    """Base class. State is a dict of int64 arrays; 'B' (cents) is always present."""
    name: str = ""
    family: str = ""
    extras: tuple = ()

    def init(self, n):
        return {k: np.zeros(n, np.int64) for k in self.extras}

    def act(self, B, st, rng=None):
        """Return (stake, required multiplier) per path, before the common clamps."""
        raise NotImplementedError

    def update(self, st, win):
        return st

    def stop(self, B, st):
        return np.zeros(len(B), bool)


def place(strategy, game, B, st, rng=None):
    """Apply the common rules: (stake, m, p) actually placed."""
    s, m_req = strategy.act(B, st, rng)
    m, p = game.quote(m_req)
    s = np.minimum(np.asarray(s, np.int64), B)
    s = np.minimum(s, stake_needed(B, m))
    s = np.maximum(s, 1)
    return s, m, p


class Bold(Strategy):
    """Bet everything (or just what is needed) at multiplier m until $100 or bust."""

    def __init__(self, m, name=None):
        super().__init__(name or f"Bold play at {m:g}x", "bold")
        self.m = m

    def act(self, B, st, rng=None):
        return B, np.full(len(B), self.m)


class TargetHit(Strategy):
    """Stake a fixed amount each time at whatever multiplier lands exactly on $100."""

    def __init__(self, stake, name=None):
        super().__init__(name or f"Target-hitting ${stake/100:g} stakes", "target")
        self.s = stake

    def act(self, B, st, rng=None):
        s = np.minimum(self.s, B)
        return s, (TARGET - B + s) / s


class PolicyTargetHit(Strategy):
    """Stake from a DP policy table (cents -> stake) at the target-hitting multiplier."""

    def __init__(self, policy, name="DP-optimal"):
        super().__init__(name, "optimal")
        self.policy = np.asarray(policy, np.int64)

    def act(self, B, st, rng=None):
        s = np.maximum(self.policy[B], 1)
        return s, (TARGET - B + s) / s


class Flat(Strategy):
    def __init__(self, stake, m=2.0, name=None, family="flat"):
        super().__init__(name or f"Flat ${stake/100:g} at {m:g}x", family)
        self.s, self.m = stake, m

    def act(self, B, st, rng=None):
        return np.full(len(B), self.s), np.full(len(B), self.m)


class FixedFraction(Strategy):
    def __init__(self, f, m=2.0):
        super().__init__(f"Fixed {f*100:g}% of bankroll at {m:g}x", "fraction")
        self.f, self.m = f, m

    def act(self, B, st, rng=None):
        return np.maximum((self.f * B).astype(np.int64), 1), np.full(len(B), self.m)


class Martingale(Strategy):
    """Double after each loss, back to base after a win."""

    def __init__(self, base, m=2.0, factor=2):
        super().__init__(f"Martingale ${base/100:g} at {m:g}x", "martingale", ("L",))
        self.base, self.m, self.factor = base, m, factor

    def act(self, B, st, rng=None):
        L = np.minimum(st["L"], 40)
        return self.base * self.factor ** L, np.full(len(B), self.m)

    def update(self, st, win):
        return {"L": np.where(win, 0, np.minimum(st["L"] + 1, 40))}


class Paroli(Strategy):
    """Reverse Martingale: double after a win, up to `wins` in a row, reset after a loss."""

    def __init__(self, base, m=2.0, wins=3):
        super().__init__(f"Reverse Martingale ${base/100:g}, {wins} wins", "reverse", ("W",))
        self.base, self.m, self.wins = base, m, wins

    def act(self, B, st, rng=None):
        return self.base * 2 ** st["W"], np.full(len(B), self.m)

    def update(self, st, win):
        W = np.where(win, st["W"] + 1, 0)
        return {"W": np.where(W >= self.wins, 0, W)}


FIB = np.array([1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610, 987, 1597, 2584, 4181,
                6765, 10946, 17711], np.int64)


class Fibonacci(Strategy):
    def __init__(self, base, m=2.0):
        super().__init__(f"Fibonacci ${base/100:g} at {m:g}x", "fibonacci", ("i",))
        self.base, self.m = base, m

    def act(self, B, st, rng=None):
        return self.base * FIB[st["i"]], np.full(len(B), self.m)

    def update(self, st, win):
        return {"i": np.where(win, np.maximum(st["i"] - 2, 0), np.minimum(st["i"] + 1, len(FIB) - 1))}


class DAlembert(Strategy):
    def __init__(self, unit, m=2.0):
        super().__init__(f"D'Alembert ${unit/100:g} units at {m:g}x", "dalembert", ("n",))
        self.unit, self.m = unit, m

    def init(self, n):
        return {"n": np.ones(n, np.int64)}

    def act(self, B, st, rng=None):
        return self.unit * st["n"], np.full(len(B), self.m)

    def update(self, st, win):
        return {"n": np.where(win, np.maximum(st["n"] - 1, 1), np.minimum(st["n"] + 1, 1000))}


class Labouchere(Strategy):
    """Cancellation system on [1,2,3,4] units: stake first+last; win crosses both off,
    a loss appends the stake; the list restarts when empty (list kept as a padded array)."""
    MAXLEN = 64

    def __init__(self, unit, m=2.0):
        super().__init__(f"Labouchere ${unit/100:g} units at {m:g}x", "labouchere", ())
        self.unit, self.m = unit, m

    def init(self, n):
        seq = np.zeros((n, self.MAXLEN), np.int64)
        seq[:, :4] = [1, 2, 3, 4]
        return {"seq": seq, "lo": np.zeros(n, np.int64), "hi": np.full(n, 3, np.int64)}

    def act(self, B, st, rng=None):
        r = np.arange(len(B))
        lo, hi = st["lo"], st["hi"]
        units = np.where(lo == hi, st["seq"][r, lo], st["seq"][r, lo] + st["seq"][r, hi])
        self._last = units
        return self.unit * units, np.full(len(B), self.m)

    def update(self, st, win):
        seq, lo, hi = st["seq"].copy(), st["lo"].copy(), st["hi"].copy()
        r = np.arange(len(lo))
        units = np.where(lo == hi, seq[r, lo], seq[r, lo] + seq[r, hi])
        single = lo == hi
        lo = np.where(win, lo + 1, lo)
        hi = np.where(win & ~single, hi - 1, hi)
        grow = ~win & (hi + 1 < self.MAXLEN)
        hi = np.where(grow, hi + 1, hi)
        seq[r[grow], hi[grow]] = units[grow]
        reset = lo > hi
        seq[reset] = 0
        seq[reset, :4] = [1, 2, 3, 4]
        lo = np.where(reset, 0, lo)
        hi = np.where(reset, 3, hi)
        return {"seq": seq, "lo": lo, "hi": hi}


class StopRule(Strategy):
    """Wrap a strategy with a stop-loss (walk away at or below `floor`) or take-profit."""

    def __init__(self, inner, floor=None, take=None):
        lab = []
        if floor is not None:
            lab.append(f"stop-loss ${floor/100:g}")
        if take is not None:
            lab.append(f"take-profit ${take/100:g}")
        super().__init__(f"{inner.name}, {' + '.join(lab)}", "stoprule", inner.extras)
        self.inner, self.floor, self.take = inner, floor, take

    def init(self, n):
        return self.inner.init(n)

    def act(self, B, st, rng=None):
        return self.inner.act(B, st, rng)

    def update(self, st, win):
        return self.inner.update(st, win)

    def stop(self, B, st):
        out = np.zeros(len(B), bool)
        if self.floor is not None:
            out |= B <= self.floor
        if self.take is not None:
            out |= B >= self.take
        return out


class RandomVariable(Strategy):
    """Variable sizing: a random 2-25% of the bankroll at a random multiplier each bet."""
    MULTS = np.array([1.5, 2.0, 3.0, 5.0, 10.0])

    def __init__(self):
        super().__init__("Random sizing 2-25% at 1.5-10x", "variable")

    def act(self, B, st, rng=None):
        f = rng.uniform(0.02, 0.25, len(B))
        m = self.MULTS[rng.integers(0, len(self.MULTS), len(B))]
        return np.maximum((f * B).astype(np.int64), 1), m


# =========================================================================== Monte Carlo
LEVELS = (2000, 3000, 5000, 7500, 10000)


def simulate(strategy, game, n=100_000, seed=0, cap=100_000, chunk=None):
    """Run n independent challenges. Returns per-path arrays and a summary dict."""
    rng = np.random.default_rng(seed)
    ids = np.arange(n)
    B = np.full(n, START, np.int64)
    st = strategy.init(n)
    bets = np.zeros(n, np.int64)
    wagered = np.zeros(n, np.int64)
    peak = B.copy()
    maxdd = np.zeros(n, np.int64)
    out_B = np.zeros(n, np.int64)
    out_bets = np.zeros(n, np.int64)
    out_wag = np.zeros(n, np.int64)
    out_peak = np.zeros(n, np.int64)
    out_dd = np.zeros(n, np.int64)
    out_end = np.zeros(n, np.int8)        # 1 target, 2 ruin, 3 stopped, 4 cap
    step = 0
    while len(ids):
        s, m, p = place(strategy, game, B, st, rng)
        win = rng.random(len(ids)) < p
        B = np.where(win, B - s + np.floor(s * m + EPS).astype(np.int64), B - s)
        st = strategy.update(st, win)
        bets += 1
        wagered += s
        peak = np.maximum(peak, B)
        maxdd = np.maximum(maxdd, peak - B)
        step += 1
        end = np.zeros(len(ids), np.int8)
        end[B >= TARGET] = 1
        end[(end == 0) & (B < 1)] = 2
        end[(end == 0) & strategy.stop(B, st)] = 3
        end[(end == 0) & (bets >= cap)] = 4
        done = end > 0
        if done.any():
            d = ids[done]
            out_B[d], out_bets[d], out_wag[d] = B[done], bets[done], wagered[done]
            out_peak[d], out_dd[d], out_end[d] = peak[done], maxdd[done], end[done]
            keep = ~done
            ids, B, bets, wagered, peak, maxdd = ids[keep], B[keep], bets[keep], wagered[keep], peak[keep], maxdd[keep]
            st = {k: v[keep] for k, v in st.items()}
    paths = dict(B=out_B, bets=out_bets, wagered=out_wag, peak=out_peak, maxdd=out_dd, end=out_end)
    return paths, summarize(paths)


def wilson(k, n, z=1.959964):
    if n == 0:
        return (np.nan, np.nan)
    ph = k / n
    den = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / den
    h = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return (c - h, c + h)


def summarize(paths) -> dict:
    n = len(paths["B"])
    B, end = paths["B"], paths["end"]
    k = int((end == 1).sum())
    fin = B / 100
    se_mean = fin.std(ddof=1) / np.sqrt(n)
    out = dict(
        n=n,
        p_target=k / n, p_target_ci=wilson(k, n),
        p_ruin=float((end == 2).mean()), p_stopped=float((end == 3).mean()), p_cap=float((end == 4).mean()),
        mean_final=float(fin.mean()), mean_final_ci=(float(fin.mean() - 1.96 * se_mean), float(fin.mean() + 1.96 * se_mean)),
        median_final=float(np.median(fin)),
        exp_profit=float(fin.mean() - START / 100),
        mean_bets=float(paths["bets"].mean()), median_bets=float(np.median(paths["bets"])),
        p90_bets=float(np.percentile(paths["bets"], 90)),
        mean_wagered=float(paths["wagered"].mean() / 100),
        median_maxdd=float(np.median(paths["maxdd"]) / 100), p90_maxdd=float(np.percentile(paths["maxdd"], 90) / 100),
        reach={str(L // 100): float((paths["peak"] >= L).mean()) for L in LEVELS},
    )
    out["reach_ci"] = {str(L // 100): wilson(int((paths["peak"] >= L).sum()), n) for L in LEVELS}
    return out


# =========================================================================== exact Markov chain
def _key(B, st):
    cols = [B] + [st[k] for k in sorted(st)]
    return np.stack(cols, axis=1)


def markov_exact(strategy, game, levels=LEVELS, max_states=3_000_000):
    """Exact absorption probabilities by enumerating every reachable state.

    Only for deterministic strategies with finite integer state (not Labouchere/random).
    Returns P(target), P(ruin), P(stopped), E[final $], E[bets], E[wagered $] and P(reach L).
    """
    names = sorted(strategy.init(1).keys())
    start = np.array([[START] + [int(strategy.init(1)[k][0]) for k in names]], np.int64)
    index = {tuple(start[0]): 0}
    states = [start[0]]
    frontier = start
    rows, cols, vals = [], [], []
    stake_of, absorbed = {}, {}
    while len(frontier):
        B = frontier[:, 0]
        st = {k: frontier[:, j + 1] for j, k in enumerate(names)}
        s, m, p = place(strategy, game, B, st)
        Bw = B - s + np.floor(s * m + EPS).astype(np.int64)
        Bl = B - s
        stw = strategy.update(st, np.ones(len(B), bool))
        stl = strategy.update(st, np.zeros(len(B), bool))
        new = []
        for nxt, pr, sto in ((Bw, p, stw), (Bl, 1 - p, stl)):
            keys = np.stack([nxt] + [sto[k] for k in names], axis=1)
            stop = strategy.stop(nxt, sto)
            for i in range(len(B)):
                src = index[tuple(frontier[i])]
                kk = tuple(keys[i])
                if nxt[i] >= TARGET:
                    kind = "T"
                elif nxt[i] < 1:
                    kind = "R"
                elif stop[i]:
                    kind = ("S", int(nxt[i]))
                else:
                    kind = None
                if kind is not None:
                    absorbed.setdefault(src, []).append((kind, float(pr[i]), int(nxt[i])))
                    continue
                j = index.get(kk)
                if j is None:
                    j = len(states)
                    index[kk] = j
                    states.append(np.array(kk))
                    new.append(kk)
                rows.append(src)
                cols.append(j)
                vals.append(float(pr[i]))
        for i in range(len(B)):
            stake_of[index[tuple(frontier[i])]] = int(s[i])
        frontier = np.array(new, np.int64) if new else np.zeros((0, 1 + len(names)), np.int64)
        if len(states) > max_states:
            raise MemoryError("state space too large")
    N = len(states)
    Q = sparse.csr_matrix((vals, (rows, cols)), shape=(N, N))
    A = (sparse.identity(N, format="csr") - Q).tocsc()
    rT = np.zeros(N)
    rR = np.zeros(N)
    rS = np.zeros(N)
    rF = np.zeros(N)
    for src, lst in absorbed.items():
        for kind, pr, nb in lst:
            if kind == "T":
                rT[src] += pr
            elif kind == "R":
                rR[src] += pr
            else:
                rS[src] += pr
            rF[src] += pr * nb / 100
    stake = np.array([stake_of[i] for i in range(N)]) / 100
    sol = spsolve(A, np.column_stack([rT, rR, rS, rF, np.ones(N), stake]))
    sol = np.atleast_2d(sol)
    res = dict(states=N, p_target=sol[0, 0], p_ruin=sol[0, 1], p_stopped=sol[0, 2],
               mean_final=sol[0, 3], mean_bets=sol[0, 4], mean_wagered=sol[0, 5])
    # P(reach level L): make B >= L absorbing
    Bcol = np.array([s[0] for s in states])
    reach = {}
    for L in levels:
        if L >= TARGET:
            reach[str(L // 100)] = res["p_target"]
            continue
        hit = Bcol >= L
        if hit[0]:
            reach[str(L // 100)] = 1.0
            continue
        keep = ~hit
        Qk = Q[keep][:, keep]
        r = np.asarray(Q[keep][:, hit].sum(axis=1)).ravel() + rT[keep]
        x = spsolve((sparse.identity(int(keep.sum()), format="csr") - Qk).tocsc(), r)
        reach[str(L // 100)] = float(np.atleast_1d(x)[0])
    res["reach"] = reach
    return res
