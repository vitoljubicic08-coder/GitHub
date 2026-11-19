"""Run the whole Roobet $10 -> $100 study and write results/roobet_results.json.

    python3 run_roobet.py            # everything (about 15-25 minutes on 4 cores)
    python3 run_roobet.py --quick    # 20,000 challenges per strategy, for a smoke test

Every strategy is simulated with 100,000 independent challenges (sample A, seed 1000+i).
Deterministic strategies are also solved exactly as Markov chains over whole-cent
bankrolls; the optimisation stage re-runs its candidates on a fresh sample B (seed 5000+i).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import blackjack as BJ  # noqa: E402
import engine as E  # noqa: E402
import exact as X  # noqa: E402
import games as G  # noqa: E402
import hilo as H  # noqa: E402
import multi as M  # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
N = 100_000


# ----------------------------------------------------------------------------- game registry
def two_outcome_game(key):
    return {
        "dice": E.Dice(0.99), "dice986": E.Dice(0.986), "dice98": E.Dice(0.98),
        "limbo": E.Limbo(0.98), "crash": E.Crash(), "slide": E.Limbo(0.98, "Slide"),
        "towers": E.towers_menu(), "wheelhigh": E.wheel_high_menu(), "coinflip": E.coinflip_menu(),
        "roulette": E.roulette_menu(True), "mines96": E.mines_menu(0.96), "mines97": E.mines_menu(0.97),
    }[key]


def strategy(key, game_key=None):
    if key == "dp":
        _, pol = X.dp_target_hit(two_outcome_game(game_key))
        return E.PolicyTargetHit(pol, "DP-optimal stakes, every bet aimed at $100")
    table = {
        "bold10": E.Bold(10.0, "One all-in bet at 10x"),
        "bold3.16": E.Bold(10 ** 0.5, "Two all-in stages at 3.16x"),
        "bold2": E.Bold(2.0, "Bold play at 2x (all-in doubling)"),
        "bold1.5": E.Bold(1.5, "Bold play at 1.5x"),
        "target1": E.TargetHit(100, "$1 stakes aimed at $100 (~91x)"),
        "flat0.5x20": E.Flat(50, 20.0, "Flat $0.50 at 20x (high-risk, low-frequency)", "highrisk"),
        "flat1x2": E.Flat(100, 2.0, "Flat $1 at 2x"),
        "flat0.1x2": E.Flat(10, 2.0, "Flat $0.10 at 2x"),
        "flat1x1.1": E.Flat(100, 1.1, "Flat $1 at 1.1x (low-risk, high-frequency)", "lowrisk"),
        "mart0.1": E.Martingale(10),
        "mart1": E.Martingale(100),
        "paroli1": E.Paroli(100, wins=3),
        "fib0.1": E.Fibonacci(10),
        "dal0.1": E.DAlembert(10),
        "lab0.1": E.Labouchere(10),
        "frac10": E.FixedFraction(0.10),
        "frac25": E.FixedFraction(0.25),
        "frac50": E.FixedFraction(0.50),
        "random": E.RandomVariable(),
        "flat1x2_sl5": E.StopRule(E.Flat(100, 2.0), floor=500),
        "flat1x2_tp50": E.StopRule(E.Flat(100, 2.0), take=5000),
        "mart0.1_tp20": E.StopRule(E.Martingale(10), take=2000),
    }
    return table[key]


MATRIX = ["bold10", "dp", "bold3.16", "bold2", "bold1.5", "target1", "flat0.5x20", "frac50", "frac25",
          "frac10", "mart1", "mart0.1", "fib0.1", "lab0.1", "dal0.1", "paroli1", "flat1x2", "flat0.1x2",
          "flat1x1.1", "random", "flat1x2_sl5", "flat1x2_tp50", "mart0.1_tp20"]
NO_EXACT = {"lab0.1", "random"}


def run_two_outcome(args):
    game_key, skey, seed, n, do_exact = args
    t = time.time()
    g = two_outcome_game(game_key)
    s = strategy(skey, game_key)
    _, sm = E.simulate(s, g, n=n, seed=seed)
    res = dict(kind="two", game=game_key, game_name=g.name, key=skey, name=s.name, family=s.family,
               seed=seed, sim=sm)
    if do_exact and skey not in NO_EXACT:
        try:
            res["exact"] = E.markov_exact(s, g)
        except MemoryError as exc:
            res["exact_error"] = str(exc)
    res["seconds"] = time.time() - t
    return res


# ----------------------------------------------------------------------------- multi-outcome games
def plinko_bets():
    pl = [G.plinko("high", 16), G.plinko("high", 13), G.plinko("high", 10), G.plinko("high", 8),
          G.plinko("medium", 16), G.plinko("medium", 12), G.plinko("low", 16)]
    return M.Bets([(b.name, b.net, b.prob, 1.0) for b in pl])


def bj_bets(variant):
    reg = BJ.regimes(variant)
    nets = BJ.nets()
    out = []
    for name, ml in (("full", 4.0), ("double", 2.0), ("none", 1.0)):
        d = reg[name]
        keep = d > 1e-15
        out.append((f"blackjack:{variant}-{name}", tuple(nets[keep]), tuple(d[keep] / d[keep].sum()), ml))
    return M.Bets(out)


def roulette_bets():
    r = [G.roulette("red"), G.roulette("bait"), G.roulette("green")]
    return M.Bets([(b.name, b.net, b.prob, 1.0) for b in r])


def run_multi(args):
    label, seed, n = args
    t = time.time()
    res = dict(kind="multi", key=label, seed=seed)
    if label.startswith("plinko"):
        bets = plinko_bets()
        if label == "plinko_dp":
            V, bo, so, it = M.dp_grid(bets, unit=25)
            strat = M.GridPolicy(25, bo, so, "DP-optimal plinko policy ($0.25 grid)")
            res["dp_value"] = float(V[G.START // 25])
            res["dp_first"] = dict(bet=bets.names[bo[G.START // 25]], stake=int(so[G.START // 25] * 25))
        elif label == "plinko_allin16":
            strat = M.AllInEach(0, "All-in on high-risk 16 rows every drop")
        else:
            strat = M.FlatEach(100, 0, "Flat $1 drops, high-risk 16 rows")
    elif label.startswith("bj"):
        variant = "enhc" if "enhc" in label else "peek"
        bets = bj_bets(variant)
        idx = {"full": 0, "double": 1, "none": 2}
        if label.endswith("_dp"):
            V, bo, so, it = M.dp_grid(bets, unit=25)
            strat = M.GridPolicy(25, bo, so, f"DP-optimal blackjack policy ({variant})")
            res["dp_value"] = float(V[G.START // 25])
            res["dp_first"] = dict(bet=bets.names[bo[G.START // 25]], stake=int(so[G.START // 25] * 25))
        elif label.endswith("_bold"):
            strat = M.BlackjackBold(1, idx, f"Blackjack all-in bold play ({variant})")
        elif label.endswith("_bold4"):
            strat = M.BlackjackBold(4, idx, f"Blackjack bold play, quarter-bankroll stakes ({variant})")
        else:
            strat = M.FlatEach(100, 0, f"Blackjack flat $1, full basic strategy ({variant})")
            # flat $1 needs $4 cover; when B < 4 dollars the clamp shrinks the stake
        res["edges"] = {nm: float(-(np.dot(b[1], b[2]))) for nm, b in zip(bets.names, bets.raw)}
    elif label == "towers_dp":
        menu = E.towers_menu()
        bets = M.Bets([(f"towers:{m:g}x", (m - 1.0, -1.0), (p, 1 - p), 1.0) for m, p in zip(menu.m, menu.p)])
        V, bo, so, it = M.dp_grid(bets, unit=25)
        strat = M.GridPolicy(25, bo, so, "DP-optimal towers policy ($0.25 grid)")
        res["dp_value"] = float(V[G.START // 25])
        res["dp_first"] = dict(bet=bets.names[bo[G.START // 25]], stake=int(so[G.START // 25] * 25))
    elif label.startswith("roulette"):
        bets = roulette_bets()
        if label == "roulette_dp":
            V, bo, so, it = M.dp_grid(bets, unit=10)
            strat = M.GridPolicy(10, bo, so, "DP-optimal roulette policy ($0.10 grid)")
            res["dp_value"] = float(V[G.START // 10])
            res["dp_first"] = dict(bet=bets.names[bo[G.START // 10]], stake=int(so[G.START // 10] * 10))
        else:
            strat = M.AllInEach(2, "Green (14x) with just enough stake to reach $100", top_net=13.0)
    else:
        raise ValueError(label)
    res["name"] = strat.name
    _, res["sim"] = M.simulate_multi(strat, bets, n=n, seed=seed)
    if not label.endswith("_dp"):
        res["exact"] = M.markov_stateless(strat, bets)
    else:
        res["exact"] = M.markov_stateless(strat, bets)          # policy evaluation of the grid policy
    res["seconds"] = time.time() - t
    return res


def run_hilo(args):
    seed, n = args
    t = time.time()
    ms = H.m_star()
    Mbest, js = H.best_plan(ms, max_steps=7)
    dp = H.FiniteSkipDP(ms)
    won, steps = dp.simulate(n, seed=seed)
    k = int(won.sum())
    return dict(kind="hilo", key="hilo", seed=seed, m_star=ms, unlimited_plan=list(js), unlimited_M=Mbest,
                unlimited_p=1 / Mbest, dp_p=dp.p_success(),
                sim=dict(n=n, p_target=k / n, p_target_ci=E.wilson(k, n), mean_steps=float(steps.mean()),
                         median_steps=float(np.median(steps)), mean_final=float(won.mean() * 10 * 0.99 * Mbest)),
                seconds=time.time() - t)


# ----------------------------------------------------------------------------- provably fair demo
def crash_point(server_seed: str, salt: str) -> float:
    """Python port of Roobet's crash verifier (crashPointFromHash)."""
    h = hmac.new(server_seed.encode(), salt.encode(), hashlib.sha256).hexdigest()
    val = 0
    o = len(h) % 4
    i = o - 4 if o > 0 else 0
    while i < len(h):
        val = ((val << 16) + int(h[max(i, 0): i + 4], 16)) % 25
        i += 4
    if val == 0:
        return 1.0
    hh = int(h[:13], 16)
    e = 2 ** 52
    return np.floor((100 * e - hh) / (e - hh)) / 100.0


def run_fairness(args):
    n, = args
    t = time.time()
    salt = "0xd751043d3a3131fefe22d75a8ae1a7cb50b5b777992cf85b95260896062a5486"   # from the verifier
    seed = hashlib.sha256(b"independent research chain, not a Roobet seed").hexdigest()
    pts = np.empty(n)
    h = seed
    for i in range(n):                    # a hash chain exactly like the live game's (in reverse)
        pts[i] = crash_point(h, salt)
        h = hashlib.sha256(h.encode()).hexdigest()
    pts = pts[::-1]
    # P(crash at exactly 1.00x) = 4% instant crashes + 1% of the rest floor to 1.00x
    out = dict(n=n, p_at_1x=float((pts == 1.0).mean()), formula_at_1x=0.04 + 0.96 * 0.01)
    for t_ in (1.5, 2.0, 10.0, 100.0):
        out[f"p_ge_{t_}"] = float((pts >= t_).mean())
        out[f"formula_{t_}"] = float(G.crash_p(t_))
    below = pts < 2.0
    streak = np.zeros(n, np.int64)
    for i in range(1, n):
        streak[i] = streak[i - 1] + 1 if below[i - 1] else 0
    cond = {}
    for k in (0, 1, 3, 5, 8):
        m = streak == k if k < 8 else streak >= k
        sel = pts[m]
        cond[str(k)] = dict(rounds=int(m.sum()), p_ge_2=float((sel >= 2).mean()) if len(sel) else None,
                            ci=E.wilson(int((sel >= 2).sum()), int(len(sel))) if len(sel) else None)
    out["after_streak_below_2x"] = cond
    x = (pts >= 2).astype(float)
    out["lag1_autocorr"] = float(np.corrcoef(x[:-1], x[1:])[0, 1])
    out["seconds"] = time.time() - t
    return out


# ----------------------------------------------------------------------------- optimisation (OOS)
OPT_CANDIDATES = ([("bold", m) for m in (1.2, 1.5, 2.0, 2.5, 3.0, 10 ** 0.5, 4.0, 10 ** (1 / 3) * 1.0, 5.0, 6.0, 8.0, 10.0)]
                  + [("frac", f, m) for f in (0.10, 0.25, 0.50, 0.75) for m in (1.5, 2.0, 3.0, 5.0)])


def cand_strategy(c):
    if c[0] == "bold":
        return E.Bold(c[1], f"Bold at {c[1]:.2f}x")
    return E.FixedFraction(c[1], c[2])


def run_opt(args):
    ci, sample, n = args
    c = OPT_CANDIDATES[ci]
    s = cand_strategy(c)
    g = E.Dice(0.99)
    seed = (1000 if sample == "A" else 5000) + 777 + ci
    _, sm = E.simulate(s, g, n=n, seed=seed)
    res = dict(kind="opt", idx=ci, cand=list(c), name=s.name, sample=sample, p_target=sm["p_target"],
               ci=sm["p_target_ci"], mean_final=sm["mean_final"], mean_bets=sm["mean_bets"])
    if sample == "A":
        res["exact"] = E.markov_exact(s, g)["p_target"]
    return res


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args()
    n = 20_000 if a.quick else N
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    jobs = []
    i = 0
    for gk in ("dice", "limbo"):
        for sk in MATRIX:
            jobs.append((run_two_outcome, (gk, sk, 1000 + i, n, True)))
            i += 1
    for gk, sks in (("crash", ("bold10", "dp", "bold2")), ("slide", ("bold10", "dp", "bold2")),
                    ("towers", ("bold10", "bold2")), ("wheelhigh", ("bold10",)), ("coinflip", ("bold2",)),
                    ("mines96", ("bold10", "dp", "bold2")), ("mines97", ("bold10", "dp", "bold2")),
                    ("dice986", ("bold10", "dp", "bold2")), ("dice98", ("bold10", "dp", "bold2"))):
        for sk in sks:
            jobs.append((run_two_outcome, (gk, sk, 1000 + i, n, True)))
            i += 1
    for gk in ("crash", "dice986", "dice98"):
        for sk in ("mart0.1", "flat1x2", "frac25"):
            jobs.append((run_two_outcome, (gk, sk, 1000 + i, n, True)))
            i += 1
    for lab in ("plinko_dp", "plinko_allin16", "plinko_flat1", "bj_peek_dp", "bj_enhc_dp", "bj_peek_bold",
                "bj_peek_bold4", "bj_peek_flat1", "bj_enhc_bold", "roulette_dp", "roulette_green", "towers_dp"):
        jobs.append((run_multi, (lab, 1000 + i, n)))
        i += 1
    jobs.append((run_hilo, (1000 + i, n)))
    i += 1
    jobs.append((run_fairness, (200_000 if not a.quick else 20_000,)))
    for ci in range(len(OPT_CANDIDATES)):
        for smp in ("A", "B"):
            jobs.append((run_opt, (ci, smp, n)))
    # longest jobs first
    slow = ("flat0.1x2", "flat1x1.1", "dal0.1", "lab0.1", "fib0.1", "mart0.1", "flat1x2")
    jobs.sort(key=lambda j: 0 if (j[0] is run_two_outcome and j[1][1] in slow) or j[0] is run_multi else 1)
    with Pool(a.procs) as pool:
        asyncs = [pool.apply_async(f, (arg,)) for f, arg in jobs]
        results = []
        for k, r in enumerate(asyncs):
            results.append(r.get())
            print(f"[{k+1}/{len(jobs)}] {time.time()-t0:7.1f}s", flush=True)
    theory = []
    for label, e in (("HiLo / Plinko / Dice (1%)", 0.01), ("Dice if 98.6%", 0.014), ("Limbo / Slide / Wheel (2%)", 0.02),
                     ("Mines/Towers/Coinflip (4%)", 0.04), ("Crash (~4.96% at high targets)", 0.0496),
                     ("Roulette (6.67%)", 1 - 14 / 15)):
        theory.append(dict(label=label, edge=e, bound=X.upper_bound(e), single=X.single_bet(1 - e),
                           timid_limit=X.timid_limit(1 - e), two_stage=X.k_stage(1 - e, 2), three_stage=X.k_stage(1 - e, 3)))
    bj = {}
    for v in ("peek", "enhc"):
        for nm, d in BJ.regimes(v).items():
            bj[f"{v}-{nm}"] = dict(ev=BJ.ev(d), dist={f"{x:g}": float(p) for x, p in zip(BJ.nets(), d) if p > 1e-12})
    payload = dict(meta=dict(n=n, start=G.START, target=G.TARGET, generated=time.strftime("%Y-%m-%d %H:%M:%S"),
                             seconds=time.time() - t0),
                   rules=G.summary_table(), theory=theory, blackjack=bj, sources=G.SOURCES,
                   results=[r for r in results if r.get("kind") in ("two", "multi", "hilo")],
                   fairness=[r for r in results if "after_streak_below_2x" in r],
                   optimisation=[r for r in results if r.get("kind") == "opt"])
    (OUT / ("roobet_results_quick.json" if a.quick else "roobet_results.json")).write_text(
        json.dumps(payload, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else float(o)))
    print("done", time.time() - t0)


if __name__ == "__main__":
    main()
