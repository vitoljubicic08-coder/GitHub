"""Phase 3: $20 -> $100. Exact solvers, Auto Bet search, 1,000,000-challenge simulations and
independent provably-fair validation. Writes results/phase3_results.json.

    python3 run_phase3.py              # full run (1,000,000 challenges per strategy)
    python3 run_phase3.py --quick      # 50,000 per strategy, for a smoke test

Seeds: strategy job i uses seed 3000 + i; provably-fair validation uses seeds 9000+.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from math import comb
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import autobet as AB  # noqa: E402
import baccarat as BC  # noqa: E402
import blackjack as BJ  # noqa: E402
import engine as E  # noqa: E402
import exact as X  # noqa: E402
import fairsim as F  # noqa: E402
import games as G  # noqa: E402
import hilo as H  # noqa: E402
import multi as M  # noqa: E402
import tabular as TB  # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
START = 2000
LV = E.LEVELS20
ROOT5 = 5 ** 0.5


# ============================================================================ shared objects
def dice(rtp=0.99):
    return E.Dice(rtp)


def union_games(rtp=0.99):
    """Every verified two-outcome bet: Dice, Limbo (= Slide), Crash, Towers, Wheel high, Roulette, Coinflip."""
    return E.BestOf([E.Dice(rtp), E.Limbo(), E.Crash(), E.towers_menu(), E.wheel_high_menu(),
                     E.roulette_menu(True), E.coinflip_menu()],
                    name="Dice + Limbo + Crash + Towers + Wheel + Roulette + Coinflip")


_CACHE = {}


def dp_policy(key, rtp=0.99):
    """Cent-exact target-hitting DP (value array, stake policy) for Dice or the union of games."""
    k = (key, rtp)
    if k not in _CACHE:
        g = dice(rtp) if key == "dice" else union_games(rtp)
        _CACHE[k] = X.dp_target_hit(g)
    return _CACHE[k]


def bj_bets(variant="peek"):
    reg = BJ.regimes(variant)
    nets = BJ.nets()
    out = []
    for name, ml in (("full", 4.0), ("double", 2.0), ("none", 1.0)):
        d = reg[name]
        keep = d > 1e-15
        out.append((f"blackjack:{variant}-{name}", tuple(nets[keep]), tuple(d[keep] / d[keep].sum()), ml))
    return M.Bets(out)


def plinko_bets():
    pl = [G.plinko("high", 16), G.plinko("high", 13), G.plinko("high", 10), G.plinko("high", 8),
          G.plinko("medium", 16), G.plinko("medium", 12), G.plinko("low", 16)]
    return M.Bets([(b.name, b.net, b.prob, 1.0) for b in pl])


def towers_bets():
    menu = E.towers_menu()
    return M.Bets([(f"towers:{m:g}x", (m - 1.0, -1.0), (p, 1 - p), 1.0) for m, p in zip(menu.m, menu.p)])


def roulette_bets():
    r = [G.roulette("red"), G.roulette("bait"), G.roulette("green")]
    return M.Bets([(b.name, b.net, b.prob, 1.0) for b in r])


def baccarat_bets():
    return M.Bets(BC.bets())


def grid_table(bets, name, unit=25):
    V, bo, so, it = M.dp_grid(bets, unit=unit)
    pol = M.GridPolicy(unit, bo, so, name)
    tab = TB.from_bets(bets, pol.act, name, "dp-multi")
    first = dict(bet=bets.names[bo[START // unit]], stake=int(so[START // unit] * unit))
    return tab, first


# ============================================================================ the candidates
def engine_candidates():
    """(key, label, family, strategy factory, game key). Game keys: dice, limbo, crash, mines97."""
    return [
        ("single_dice", "One bet: all $20 on Dice at 19.80% (5.00x)", "single", lambda: E.Bold(5.0), "dice"),
        ("single_limbo", "One bet: all $20 on Limbo at 5x", "single", lambda: E.Bold(5.0), "limbo"),
        ("single_crash", "One bet: all $20 on Crash, auto-cashout 5x", "single", lambda: E.Bold(5.0), "crash"),
        ("single_mines97", "One bet: Mines at about 5x (if RTP 97%, unverified)", "single", lambda: E.Bold(5.0), "mines97"),
        ("dp_dice", "Optimal policy (DP), Dice: stakes by bankroll, every bet aimed at $100", "optimal",
         lambda: E.PolicyTargetHit(dp_policy("dice")[1], "Optimal policy (DP), Dice"), "dice"),
        ("two_stage", "Two all-in stages at 2.236x", "multi", lambda: E.Bold(ROOT5), "dice"),
        ("bold2", "Bold play at 2x (all-in, or what is needed)", "multi", lambda: E.Bold(2.0), "dice"),
        ("bold10", "Needed-only bets at 9.9x (all-in once short)", "multi", lambda: E.Bold(9.9), "dice"),
        ("bold99", "Needed-only bets at 99x", "multi", lambda: E.Bold(99.0), "dice"),
        ("target1", "$1 stakes aimed at $100", "multi", lambda: E.TargetHit(100), "dice"),
        ("tfrac25", "25% of bankroll aimed at $100", "multi", lambda: E.TargetFraction(0.25), "dice"),
        ("frac50", "Fixed 50% of bankroll at 2x", "fraction", lambda: E.FixedFraction(0.50), "dice"),
        ("frac25", "Fixed 25% of bankroll at 2x", "fraction", lambda: E.FixedFraction(0.25), "dice"),
        ("alt", "Alternate 2x / 10x bets, 25% of bankroll", "custom", lambda: E.Alternate(0.25, 2.0, 10.0), "dice"),
        ("mart0.1", "Martingale $0.10 at 2x (by hand)", "progressive-loss", lambda: E.Martingale(10), "dice"),
        ("fib0.1", "Fibonacci $0.10 at 2x", "progressive-loss", lambda: E.Fibonacci(10), "dice"),
        ("dal0.1", "D'Alembert $0.10 at 2x", "progressive-loss", lambda: E.DAlembert(10), "dice"),
        ("lab0.1", "Labouchere $0.10 (1-2-3-4) at 2x", "progressive-loss", lambda: E.Labouchere(10), "dice"),
        ("paroli1", "Reverse Martingale $1, up to 3 wins", "progressive-win", lambda: E.Paroli(100, wins=3), "dice"),
        ("flat1x2", "Flat $1 at 2x", "flat", lambda: E.Flat(100, 2.0), "dice"),
        ("flat1x1.1", "Flat $1 at 1.1x (low risk, high frequency)", "flat", lambda: E.Flat(100, 1.1), "dice"),
        ("flat0.5x20", "Flat $0.50 at 20x (high risk, low frequency)", "flat", lambda: E.Flat(50, 20.0), "dice"),
        ("random", "Random 2-25% of bankroll at random 1.5-10x", "custom", lambda: E.RandomVariable(), "dice"),
        ("flat_sl10", "Flat $1 at 2x with stop-loss at $10", "stop-rule", lambda: E.StopRule(E.Flat(100, 2.0), floor=1000), "dice"),
        ("flat_tp60", "Flat $1 at 2x with take-profit at $60", "stop-rule", lambda: E.StopRule(E.Flat(100, 2.0), take=6000), "dice"),
    ]


def autobet_candidates(best):
    """Auto Bet configurations. `best` holds the searched geometric settings."""
    g_pure, g_fin = best["pure_multi"], best["finish_multi"]
    pol = dp_policy("dice")[1]
    return [
        ("ab_single", "Auto Bet: $20 at 19.80%, Number of Bets 1", "autobet",
         lambda: AB.AutoBet(2000, 5.0, start=START, stop_profit=8000), "dice"),
        ("ab_geo", f"Auto Bet: Dice {g_pure['chance']:g}%, ${g_pure['base']/100:.2f}, on loss +{g_pure['pct']*100:g}%, "
                   f"on win reset, stop on profit $80", "autobet",
         lambda: AB.AutoBet(g_pure["base"], 99 / g_pure["chance"], on_loss="increase", loss_pct=g_pure["pct"],
                            stop_profit=8000, start=START, name="Auto Bet geometric (best found)"), "dice"),
        ("ab_geo_finish", f"Auto Bet: Dice {g_fin['chance']:g}%, ${g_fin['base']/100:.2f}, on loss +{g_fin['pct']*100:g}%, "
                          f"then the rest by hand (DP)", "autobet+manual",
         lambda: AB.AutoBet(g_fin["base"], 99 / g_fin["chance"], on_loss="increase", loss_pct=g_fin["pct"],
                            stop_profit=8000, start=START, finish=pol, name="Auto Bet geometric + finish"), "dice"),
        ("ab_mart0.1", "Auto Bet Martingale: $0.10 at 2x (49.5%), on loss +100%, on win reset, stop on profit $80",
         "autobet", lambda: AB.AutoBet(10, 2.0, on_loss="increase", loss_pct=1.0, stop_profit=8000, start=START), "dice"),
        ("ab_mart1", "Auto Bet Martingale: $1 at 2x, on loss +100%, on win reset, stop on profit $80", "autobet",
         lambda: AB.AutoBet(100, 2.0, on_loss="increase", loss_pct=1.0, stop_profit=8000, start=START), "dice"),
        ("ab_mart3x", "Auto Bet: $0.50 at 3x (33%), on loss +50%, on win reset, stop on profit $80", "autobet",
         lambda: AB.AutoBet(50, 3.0, on_loss="increase", loss_pct=0.5, stop_profit=8000, start=START), "dice"),
        ("ab_paroli", "Auto Bet Paroli: $1 at 2x, on win +100%, on loss reset, stop on profit $80", "autobet",
         lambda: AB.AutoBet(100, 2.0, on_win="increase", win_pct=1.0, stop_profit=8000, start=START), "dice"),
        ("ab_ride", "Auto Bet let-it-ride: $20 at 2.2363x (44.27%), on win +123.6%, stop on profit $80", "autobet",
         lambda: AB.AutoBet(2000, 99 / 44.27, on_win="increase", win_pct=1.236, stop_profit=8000, start=START), "dice"),
        ("ab_flat", "Auto Bet flat: $1 at 2x, stop on profit $80", "autobet",
         lambda: AB.AutoBet(100, 2.0, stop_profit=8000, start=START), "dice"),
        ("ab_flat_sl", "Auto Bet flat: $1 at 2x, stop on loss $10, stop on profit $80", "autobet",
         lambda: AB.AutoBet(100, 2.0, stop_profit=8000, stop_loss=1000, start=START), "dice"),
        ("ab_crash_mart", "Auto Bet Crash: cash-out 2x, $0.10, on loss +100%, stop on profit $80", "autobet",
         lambda: AB.AutoBet(10, 2.0, on_loss="increase", loss_pct=1.0, stop_profit=8000, start=START), "crash"),
        ("ab_limbo_geo", "Auto Bet Limbo: target 10x, $8.89, on loss +11.12%, stop on profit $80", "autobet",
         lambda: AB.AutoBet(889, 10.0, on_loss="increase", loss_pct=0.1112, stop_profit=8000, start=START), "limbo"),
    ]


def game_of(key, rtp=0.99):
    return {"dice": lambda: E.Dice(rtp), "limbo": lambda: E.Limbo(), "crash": lambda: E.Crash(),
            "mines97": lambda: E.mines_menu(0.97), "mines96": lambda: E.mines_menu(0.96)}[key]()


NO_EXACT = {"lab0.1", "random"}


def table_candidates():
    """Policies evaluated as transition tables (multi-game and multi-outcome)."""
    return [
        ("dp_union", "Optimal policy (DP) over every verified two-outcome game (switches game per bet)", "optimal"),
        ("bj_dp", "Blackjack: optimal stakes with full basic strategy (dealer peeks)", "game-dp"),
        ("bac_dp", "Baccarat (third-party live; standard rules): optimal stakes", "game-dp"),
        ("plinko_dp", "Plinko: optimal table and stakes", "game-dp"),
        ("towers_dp", "Towers: optimal level and stakes", "game-dp"),
        ("roulette_dp", "Roulette: optimal colour and stakes", "game-dp"),
        ("mix_bj_dice", "Blackjack at 1/4 bankroll until $50, then one Dice bet to $100", "custom"),
    ]


def build_table(key):
    if key == "dp_union":
        V, pol = dp_policy("union")
        return TB.two_outcome(union_games(), lambda B: pol[B], "Optimal policy (DP), all two-outcome games", "optimal"), {}
    if key == "bj_dp":
        return grid_table(bj_bets("peek"), "Blackjack DP")
    if key == "bac_dp":
        return grid_table(baccarat_bets(), "Baccarat DP")
    if key == "plinko_dp":
        return grid_table(plinko_bets(), "Plinko DP")
    if key == "towers_dp":
        return grid_table(towers_bets(), "Towers DP")
    if key == "roulette_dp":
        return grid_table(roulette_bets(), "Roulette DP", unit=10)
    if key == "mix_bj_dice":
        bets = bj_bets("peek")
        t_bj = TB.from_bets(bets, lambda B: (np.maximum(B // 4, 1), np.zeros(len(B), np.int64)), "bj")
        t_d = TB.two_outcome(E.Dice(), lambda B: B, "dice all-in")
        return TB.mix([t_bj, t_d], lambda B: (B >= 5000).astype(int), "Blackjack then Dice"), {}
    raise KeyError(key)


# ============================================================================ jobs
def job_engine(args):
    key, seed, n, best = args
    t = time.time()
    _, label, family, factory, gkey = {c[0]: c for c in engine_candidates() + autobet_candidates(best)}[key]
    s, g = factory(), game_of(gkey)
    res = dict(kind="engine", key=key, label=label, family=family, game=g.name, seed=seed)
    _, res["sim"] = E.simulate(s, g, n=n, seed=seed, start=START, levels=LV, cap=200_000)
    if key not in NO_EXACT:
        res["exact"] = E.markov_exact(s, g, levels=LV, start=START)
        if gkey == "dice" and key != "ab_geo_finish":
            # Dice paying 98.6% or 98% instead of 99%: same rules, multipliers kept, chances cut;
            # the DP policy is re-optimised for the lower RTP.
            sens = {}
            for rtp in (0.986, 0.98):
                s2 = E.PolicyTargetHit(dp_policy("dice", rtp)[1]) if key == "dp_dice" else factory()
                sens[str(rtp)] = E.markov_exact(s2, E.Dice(rtp), levels=LV, start=START)["p_target"]
            res["sensitivity"] = sens
    res["seconds"] = time.time() - t
    return res


def job_table(args):
    key, label, family, seed, n = args
    t = time.time()
    tab, first = build_table(key)
    res = dict(kind="table", key=key, label=label, family=family, seed=seed, first=first)
    res["exact"] = {k: v for k, v in TB.evaluate(tab, START, LV).items() if k != "V"}
    _, res["sim"] = TB.simulate(tab, n=n, seed=seed, start=START, levels=LV)
    if key == "dp_union":
        # which game the policy uses, by bankroll
        g = np.asarray(tab.game)
        res["games_used"] = {union_games().games[k].name: int((g[1:] == k).sum()) for k in np.unique(g[1:])}
    res["seconds"] = time.time() - t
    return res


def job_hilo(args):
    seed, n = args
    t = time.time()
    ms = H.m_star(stake=20.0)
    Mb, js = H.best_plan(ms, max_steps=8)
    dp = H.FiniteSkipDP(ms)
    won, steps = dp.simulate(n, seed=seed)
    k = int(won.sum())
    return dict(kind="hilo", key="hilo", label="HiLo: one $20 round played to >= 5.0505x",
                family="single", seed=seed, m_star=ms, plan=list(js), M=Mb, p_unlimited=1 / Mb,
                exact=dict(p_target=dp.p_success()),
                sim=dict(n=n, p_target=k / n, p_target_ci=E.wilson(k, n), mean_bets=float(steps.mean()),
                         median_bets=float(np.median(steps))), seconds=time.time() - t)


def job_fair(args):
    what, seed, n, extra = args
    t = time.time()
    if what == "rolls":
        h = np.array(F.roll_frequencies(n, seed))
        exp = n / 100
        return dict(kind="fair", what=what, n=n, chi2=float(((h - exp) ** 2 / exp).sum()), dof=99, seconds=time.time() - t)
    if what == "single":
        pol = np.arange(G.TARGET)                        # all-in, aimed at $100
        r = F.play_policy(pol, n, seed)
    elif what == "dp":
        r = F.play_policy(dp_policy("dice")[1], n, seed)
    elif what == "geo":
        r = F.play_autobet(extra["base"], int(round(extra["chance"] * 100)), extra["pct"], n, seed)
    elif what == "geo_finish":
        r = F.play_autobet(extra["base"], int(round(extra["chance"] * 100)), extra["pct"], n, seed,
                           finish=dp_policy("dice")[1])
    elif what == "mart":
        r = F.play_autobet(10, 4950, 1.0, n, seed)
    k = int(round(r["p_target"] * n))
    r.update(kind="fair", what=what, p_target_ci=E.wilson(k, n), seconds=time.time() - t)
    return r


# ============================================================================ analyses (main process)
def theory():
    rows = []
    for label, e in (("Dice, HiLo, Plinko (1%)", 0.01), ("Dice if 98.6%", 0.014), ("Limbo, Slide, Wheel (2%)", 0.02),
                     ("Towers, Mines, Coinflip (4%)", 0.04), ("Crash (4.96% at high targets)", 0.0496),
                     ("Roulette (6.67%)", 1 - 14 / 15)):
        r = 1 - e
        row = dict(label=label, edge=e)
        for b in (1000, 2000):
            row[f"bound_{b}"] = X.upper_bound(e, b)
            row[f"single_{b}"] = X.single_bet(r, b)
            row[f"continuous_{b}"] = X.timid_limit(r, b)
            row[f"two_stage_{b}"] = X.k_stage(r, 2, b)
        rows.append(row)
    return rows


def policy_table():
    """The DP policies by bankroll: stake, multiplier, win chance, game, value."""
    out = {}
    for key in ("dice", "union"):
        V, pol = dp_policy(key)
        g = dice() if key == "dice" else union_games()
        P, Fm, W, K = X.target_hit_stats(g, pol)
        rows = []
        for b in (100, 500, 1000, 2000, 3000, 4000, 5000, 6000, 8000, 9000, 9500, 9900):
            s = int(pol[b])
            m_req = (G.TARGET - b + s) / s
            if key == "dice":
                m, p = g.quote(np.array([m_req]))
                gname = "Dice"
            else:
                m, p, gi = g.choose(np.array([m_req]))
                gname = g.games[int(gi[0])].name
            rows.append(dict(bankroll=b / 100, stake=s / 100, share=s / b, multiplier=float(m[0]), p_win=float(p[0]),
                             game=gname, V=float(V[b]), single=0.99 * b / G.TARGET if b >= 102 else None,
                             continuous=1 - (1 - b / G.TARGET) ** 0.99, exp_bets=float(K[b]), exp_wagered=float(W[b])))
        out[key] = dict(V20=float(V[START]), V10=float(V[1000]), rows=rows,
                        exp_wagered20=float(W[START]), exp_bets20=float(K[START]), exp_final20=float(Fm[START]))
    return out


def optimality_checks():
    """Is aiming every bet at $100 with two-outcome games optimal over everything else?"""
    Vd, _ = dp_policy("dice")
    Vu, _ = dp_policy("union")
    res = dict(V_dice=float(Vd[START]), V_union=float(Vu[START]), union_gain=float(Vu[START] - Vd[START]))
    # (1) idealised casino, $0.50 grid: allowing landing points below $100 changes nothing?
    Vi, _ = X.dp_continuous(0.99, unit=50, allow_intermediate=True, iters=300)
    Vt, _ = X.dp_continuous(0.99, unit=50, allow_intermediate=False, iters=300)
    res["grid_intermediate"] = float(Vi[START // 50])
    res["grid_target_only"] = float(Vt[START // 50])
    # (2) sampled two-outcome bets that land below $100, against the union value
    res["sampled_two_outcome"] = X.sampled_two_outcome_check(Vu, union_games(), n=20_000_000, seed=11)
    # (3) exhaustive one-step check of every multi-outcome bet against the union value
    checks = {}
    for name, nets, probs, ml in (list(bj_bets("peek").raw) + list(BC.bets()) + list(plinko_bets().raw)
                                  + [(f"wheel:{d}-{s}", G.wheel(d, s).net, G.wheel(d, s).prob, 1.0)
                                     for d, s in (("low", 10), ("medium", 10), ("medium", 50))]):
        checks[name] = X.max_improvement(Vu, nets, probs, ml)
    res["multi_outcome_checks"] = checks
    res["multi_outcome_checks_from_1usd"] = {
        name: X.max_improvement(Vu, nets, probs, ml, b_lo=100)
        for name, nets, probs, ml in (list(bj_bets("peek").raw) + list(BC.bets()) + list(plinko_bets().raw))}
    res["sampled_two_outcome_from_1usd"] = X.sampled_two_outcome_check(Vu, union_games(), n=20_000_000, seed=12, b_lo=100)
    # Any strategy's chance from b is at most the ceiling (10 - e b')/(100 - e b'); below $1 the
    # DP is within this gap of it, so improvements found there move V($20) by at most this much.
    b = np.arange(1, 100)
    res["max_gap_below_1usd"] = float(np.max(X.upper_bound(0.01, b) - Vu[b]))
    return res


def search_geometric(V, start=START, pct_decimals=2, chances=None):
    """Exact search of the 'every win lands on $100' Auto Bet family on Dice.

    For each win chance, base bet and loss increase (as typed, 2 decimals of a percent),
    the losing run is deterministic: stakes s_0, s_1, ... until the next one no longer fits.
    If every win along it lands on >= $100, P = 1 - (1-p)^n exactly (pure Auto Bet; the
    leftover is kept) or adds (1-p)^n * V(leftover) when the rest is played by hand.
    """
    if chances is None:
        chances = sorted(set(np.round(np.geomspace(0.05, 19.8, 160), 2).tolist() + [19.8]))
    q = 10 ** pct_decimals
    best = {"pure": None, "finish": None, "pure_multi": None, "finish_multi": None}
    rows = []
    for c in chances:
        m = 99.0 / c
        p = c / 100
        if m < 5.0 - 1e-9:
            continue
        b0 = int(np.ceil((G.TARGET - start) / (m - 1) - E.EPS))
        p0 = np.ceil(100.0 / (m - 1) * q - E.EPS) / q
        top = (None, -1)
        topf = (None, -1)
        topm = (None, -1)
        topfm = (None, -1)
        for base in range(b0, min(b0 + 80, start) + 1):
            for dp_ in range(0, 61):
                pct = (p0 + dp_ / q) / 100
                B, j, n, ok, Pw = start, 0, 0, True, 0.0
                surv = 1.0
                while True:
                    s = int(np.floor(base * (1 + pct) ** j + 0.5 + E.EPS))
                    if s > B:
                        break
                    if B - s + np.floor(s * m + E.EPS) < G.TARGET:
                        ok = False
                        break
                    Pw += surv * p
                    surv *= 1 - p
                    B -= s
                    j += 1
                    n += 1
                if not ok:
                    continue
                if Pw > top[1] + 1e-15:
                    top = (dict(chance=c, base=base, pct=pct, bets=n, leftover=B), Pw)
                Pf = Pw + surv * V[B]
                cfg = dict(chance=c, base=base, pct=pct, bets=n, leftover=B)
                if Pf > topf[1] + 1e-15:
                    topf = (cfg, Pf)
                if n >= 2 and Pw > topm[1] + 1e-15:
                    topm = (cfg, Pw)
                if n >= 2 and Pf > topfm[1] + 1e-15:
                    topfm = (cfg, Pf)
        if top[0] is not None:
            rows.append(dict(chance=c, mult=m, pure=top[1], pure_cfg=top[0], finish=topf[1], finish_cfg=topf[0]))
            if best["pure"] is None or top[1] > best["pure"]["P"]:
                best["pure"] = dict(top[0], P=top[1])
            if best["finish"] is None or topf[1] > best["finish"]["P"]:
                best["finish"] = dict(topf[0], P=topf[1])
            if topm[0] is not None and (best["pure_multi"] is None or topm[1] > best["pure_multi"]["P"]):
                best["pure_multi"] = dict(topm[0], P=topm[1])
            if topfm[0] is not None and (best["finish_multi"] is None or topfm[1] > best["finish_multi"]["P"]):
                best["finish_multi"] = dict(topfm[0], P=topfm[1])
    # the same search if any percentage could be typed (no rounding of the increase)
    return best, rows


def compare_10_20():
    """$10 vs $20 for the same rule sets, exact."""
    out = []
    V, pol = dp_policy("dice")
    pairs = [
        ("One all-in bet aimed at $100", lambda b: E.Bold(10.0 if b == 1000 else 5.0)),
        ("Optimal policy (DP), Dice", lambda b: E.PolicyTargetHit(pol)),
        ("Two all-in stages", lambda b: E.Bold(10 ** 0.5 if b == 1000 else ROOT5)),
        ("Bold play at 2x", lambda b: E.Bold(2.0)),
        ("Fixed 25% of bankroll at 2x", lambda b: E.FixedFraction(0.25)),
        ("Martingale $0.10", lambda b: E.Martingale(10)),
        ("Fibonacci $0.10", lambda b: E.Fibonacci(10)),
        ("D'Alembert $0.10", lambda b: E.DAlembert(10)),
        ("Flat $1 at 2x", lambda b: E.Flat(100, 2.0)),
        ("Flat $1 at 1.1x", lambda b: E.Flat(100, 1.1)),
    ]
    for label, mk in pairs:
        row = dict(label=label)
        for b in (1000, 2000):
            lv = E.LEVELS if b == 1000 else LV
            ex = E.markov_exact(mk(b), E.Dice(), levels=lv, start=b)
            row[str(b)] = dict(p=ex["p_target"], loss=b / 100 - ex["mean_final"], wagered=ex["mean_wagered"],
                               bets=ex["mean_bets"], sd=ex["sd_final"], ruin=ex["p_ruin"])
        out.append(row)
    return out


def hilo_plans():
    rows = []
    for stake in (10.0, 20.0):
        ms = H.m_star(stake=stake)
        Mb, js = H.best_plan(ms, max_steps=8)
        rows.append(dict(stake=stake, m_star=ms, M=Mb, plan=list(js), p=1 / Mb, ceiling=1 / ms))
    return rows


# ============================================================================ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args()
    n = 50_000 if a.quick else 1_000_000
    nf = 20_000 if a.quick else 200_000
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    log = lambda msg: print(f"{time.time()-t0:7.1f}s {msg}", flush=True)

    V, _ = dp_policy("dice")
    log("dice DP done")
    best, geo_rows = search_geometric(V)
    log(f"geometric search: pure {best['pure']}, finish {best['finish']}")
    best_any, _ = search_geometric(V, pct_decimals=4)
    log(f"geometric search (any percentage): {best_any}")

    jobs = []
    i = 0
    for c in engine_candidates() + autobet_candidates(best):
        jobs.append((job_engine, (c[0], 3000 + i, n, best)))
        i += 1
    for key, label, family in table_candidates():
        jobs.append((job_table, (key, label, family, 3000 + i, n)))
        i += 1
    jobs.append((job_hilo, (3000 + i, n)))
    fair = [("rolls", 9000, 1_000_000 if not a.quick else 50_000, {}), ("single", 9001, n, {}),
            ("dp", 9002, nf, {}), ("geo", 9003, nf, best["pure_multi"]), ("geo_finish", 9004, nf, best["finish_multi"]),
            ("mart", 9005, nf // 5, {})]
    for w, sd, nn, ex in fair:
        jobs.append((job_fair, (w, sd, nn, ex)))
    slow = {"flat1x2", "flat1x1.1", "fib0.1", "dal0.1", "lab0.1", "mart0.1", "ab_mart0.1", "ab_flat", "ab_crash_mart",
            "flat_tp60", "random", "frac25", "alt", "paroli1", "ab_paroli"}
    jobs.sort(key=lambda j: 0 if (j[1][0] in slow or j[0] is job_fair) else 1)

    with Pool(a.procs) as pool:
        asyncs = [pool.apply_async(f, (arg,)) for f, arg in jobs]
        # main-process analyses while the pool works
        th = theory()
        pt = policy_table()
        log("policy table done")
        cmp_ = compare_10_20()
        log("10 vs 20 done")
        hp = hilo_plans()
        oc = optimality_checks()
        log("optimality checks done")
        results = []
        for k, r in enumerate(asyncs):
            results.append(r.get())
            log(f"job {k+1}/{len(jobs)} {results[-1].get('key', results[-1].get('what'))}")
    payload = dict(meta=dict(n=n, start=START, target=G.TARGET, generated=time.strftime("%Y-%m-%d %H:%M:%S"),
                             seconds=time.time() - t0),
                   theory=th, policy=pt, compare_10_20=cmp_, hilo_plans=hp, optimality=oc,
                   geometric=dict(best=best, best_any_pct=best_any, rows=geo_rows),
                   baccarat=BC.outcome_probs(8),
                   results=[r for r in results if r["kind"] in ("engine", "table", "hilo")],
                   fair=[r for r in results if r["kind"] == "fair"])
    name = "phase3_results_quick.json" if a.quick else "phase3_results.json"
    (OUT / name).write_text(json.dumps(payload, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else float(o)))
    log("done")


if __name__ == "__main__":
    main()
