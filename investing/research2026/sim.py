"""Simulation engine for 24-month (and longer) portfolio outcomes in euros.

Path generators (all joint across sleeves, so overlaps and correlations between holdings are kept):
  bootstrap_raw      stationary block bootstrap of historical monthly euro log returns (Politis-Romano,
                     mean block 6 months, circular). "History repeats", including its winners: biased upward
                     for the US tech sleeves that we only call "tech winners" with hindsight.
  bootstrap_forward  the same blocks, each sleeve re-centred to a forward-looking expected return under one
                     of four scenarios (an equal-weight ensemble). Keeps fat tails, crash clustering and
                     correlations; removes the hindsight in average returns. THE HEADLINE MODEL.
  t_mc               correlated multivariate Student-t (5 degrees of freedom) Monte Carlo with consensus
                     expected returns and per-path uncertainty in the equity premium.

Expected returns are CAPM-consistent (no assumed skill or sector edge): E[r_i] = rf + beta_i * (E[r_world] - rf),
plus an explicit "AI" tilt in the AI-bull / AI-bust scenarios. All are assumptions, stated in SCENARIOS.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RF = 0.024                      # euro cash (EUR STR 2.44% on 17 Nov 2026), annual
SCENARIOS = {                   # annual compound expected returns in euros (assumptions; see report s8, s16)
    "cautious": {"world": 0.055, "gold": 0.035, "ai_alpha": 0.00},    # Vanguard-like (US 4.8-6.8%)
    "consensus": {"world": 0.070, "gold": 0.055, "ai_alpha": 0.00},   # J.P. Morgan 2027 LTCMA-like (US 7.5%)
    "ai_bull": {"world": 0.085, "gold": 0.035, "ai_alpha": 0.04},     # AI earnings keep beating
    "ai_bust": {"world": 0.035, "gold": 0.065, "ai_alpha": -0.08},    # AI capex pause / de-rating
}
# how strongly each sleeve's return depends on the AI investment cycle (my judgement, 0 = none)
AI_EXPOSURE = {"NDX": 0.5, "SEMI": 1.0, "NVDA": 1.3, "TECH": 0.6, "MEGA8": 0.8, "SPEC": 0.3, "ARKK": 0.6,
               "MOMENTUM": 0.3, "SPX": 0.3, "WORLD": 0.2, "QUALITY": 0.2, "UTIL": 0.2,
               "AVGO": 1.0, "TSM": 1.0, "AMD": 1.0, "ASML": 0.8, "MU": 1.0, "MSFT": 0.5, "GOOGL": 0.5,
               "AMZN": 0.4, "META": 0.5, "ORCL": 0.7, "PLTR": 0.8, "AAPL": 0.2}
NON_EQUITY = ("CASH", "GOLD")
TRADE_COST = {"CASH": 0.0002, "NVDA": 0.0018}                  # one-way; ETFs default 0.10%, US stocks 0.18%
US_STOCKS = ("MSFT", "AAPL", "GOOGL", "AMZN", "META", "AVGO", "TSM", "AMD", "ASML", "MU", "ORCL", "PLTR",
             "TSLA", "NFLX", "LLY", "NVO", "JPM", "V", "MA", "COST", "BRK-B", "UNH", "SAP")
TAX = 0.12


def trade_cost(sleeve: str) -> float:
    if sleeve in TRADE_COST:
        return TRADE_COST[sleeve]
    return 0.0018 if sleeve in US_STOCKS else 0.0010


def log_returns(mm: pd.DataFrame, cols, start, end) -> pd.DataFrame:
    x = np.log1p(mm.loc[start:end, list(cols)])
    return x.dropna()


def betas(X: pd.DataFrame) -> pd.Series:
    """Beta of each sleeve's monthly excess log return on the world sleeve's."""
    ex = X.sub(X["CASH"], axis=0)
    m = ex["WORLD"]
    return ex.apply(lambda c: np.cov(c, m)[0, 1] / m.var())


SLOPES = (1.0, 0.5)             # reward per unit of beta: CAPM (1.0) and the flatter line seen in practice (0.5)


def forward_mu(cols, beta: pd.Series, scn: dict, slope: float = 1.0) -> np.ndarray:
    """Monthly log drift per sleeve. slope < 1 flattens the reward for beta around the world portfolio
    (beta 1 keeps the world return): high-beta assets have historically earned less than CAPM implies
    (Frazzini and Pedersen, "Betting against beta", 2014)."""
    out = []
    for c in cols:
        if c == "CASH":
            mu = RF
        elif c == "GOLD":
            mu = scn["gold"]
        else:
            b = 1 + slope * (beta[c] - 1)
            mu = RF + b * (scn["world"] - RF) + AI_EXPOSURE.get(c, 0.0) * scn["ai_alpha"]
        out.append(np.log1p(mu) / 12)                                  # monthly log drift (median growth)
    return np.array(out)


def stationary_bootstrap(n_obs: int, n_paths: int, horizon: int, mean_block: float, rng) -> np.ndarray:
    idx = np.empty((n_paths, horizon), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n_obs, n_paths)
    new = rng.random((n_paths, horizon)) < 1.0 / mean_block
    jump = rng.integers(0, n_obs, (n_paths, horizon))
    for t in range(1, horizon):
        idx[:, t] = np.where(new[:, t], jump[:, t], (idx[:, t - 1] + 1) % n_obs)
    return idx


def bootstrap_raw(X: pd.DataFrame, n_paths=10_000, horizon=24, mean_block=6, seed=1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    idx = stationary_bootstrap(len(X), n_paths, horizon, mean_block, rng)
    return X.to_numpy()[idx]                                           # (paths, months, sleeves) log returns


def bootstrap_forward(X: pd.DataFrame, n_paths=10_000, horizon=24, mean_block=6, seed=2, scenarios=None,
                      slopes=SLOPES):
    """Re-centred bootstrap; path k uses the k-th (scenario, slope) pair, cycling, so the 10,000 paths split
    equally across 4 scenarios x 2 beta slopes. Returns (paths, labels "scenario/slope")."""
    scenarios = scenarios or list(SCENARIOS)
    combos = [(s, sl) for s in scenarios for sl in slopes]
    rng = np.random.default_rng(seed)
    idx = stationary_bootstrap(len(X), n_paths, horizon, mean_block, rng)
    A = X.to_numpy()
    base = A - A.mean(axis=0)
    b = betas(X)
    R = base[idx]
    lab = np.array([f"{combos[k % len(combos)][0]}/{combos[k % len(combos)][1]}" for k in range(n_paths)])
    for s, sl in combos:
        R[lab == f"{s}/{sl}"] += forward_mu(X.columns, b, SCENARIOS[s], sl)
    return R, lab


def t_mc(X: pd.DataFrame, n_paths=10_000, horizon=24, nu=5, seed=3, scenario="consensus", premium_sd=0.02):
    rng = np.random.default_rng(seed)
    cols = list(X.columns)
    b = betas(X)
    mu = forward_mu(cols, b, SCENARIOS[scenario])
    cov = np.cov(X.to_numpy().T) * (nu - 2) / nu
    L = np.linalg.cholesky(cov + 1e-12 * np.eye(len(cols)))
    z = rng.standard_normal((n_paths, horizon, len(cols))) @ L.T
    w = rng.chisquare(nu, (n_paths, horizon, 1)) / nu
    eq = np.array([0.0 if c in NON_EQUITY else b[c] for c in cols])
    shock = rng.normal(0, premium_sd, (n_paths, 1, 1)) * eq / 12       # per-path equity-premium uncertainty
    return mu + z / np.sqrt(w) + shock


# --------------------------------------------------------------------------------------------- portfolios

def simulate(R: np.ndarray, cols, port: dict, initial=5000.0, contrib=0.0, method="target",
             rebalance_month=12, horizon=None, tax_horizon=None):
    """Holdings-level simulation with tax lots.

    R: (paths, months, sleeves) monthly log returns. Deposits: `initial` at month 0, `contrib` at the end of
    months 1..T. method: "target" (split by target weights; Trading 212 AutoInvest), "self_balance" (buy
    underweight slices first; Trading 212 "Self-balance" when adding funds), "target_rebal" (target plus a
    full sell-and-buy rebalance at `rebalance_month`, taxable). Returns monthly values and liquidation values.
    """
    T = R.shape[1] if horizon is None else horizon
    n = R.shape[0]
    j = [cols.index(k) for k in port]
    w = np.array([port[k] for k in port])
    G = np.exp(R[:, :T, j])
    tc = np.array([trade_cost(k) for k in port])
    Hi = np.tile(initial * w * (1 - tc), (n, 1))                       # initial lot (month 0)
    Bi = np.tile(initial * w, (n, 1))
    Hc = np.zeros_like(Hi)                                             # later purchases (all < 24 months old)
    Bc = np.zeros_like(Hi)
    V = np.empty((n, T + 1))
    V[:, 0] = Hi.sum(1)
    dep = np.empty(T + 1)
    dep[0] = initial
    tax_paid = np.zeros(n)
    for t in range(1, T + 1):
        Hi *= G[:, t - 1]
        Hc *= G[:, t - 1]
        if method == "target_rebal" and t == rebalance_month:
            H = Hi + Hc
            tgt = H.sum(1, keepdims=True) * w
            sell = np.maximum(H - tgt, 0)
            from_i = np.minimum(sell, Hi)                               # FIFO: oldest (initial) lot first
            from_c = sell - from_i
            with np.errstate(invalid="ignore", divide="ignore"):
                gi = np.where(Hi > 0, from_i * (1 - Bi / Hi), 0)
                gc = np.where(Hc > 0, from_c * (1 - Bc / Hc), 0)
                Bi = np.where(Hi > 0, Bi * (1 - from_i / Hi), 0)
                Bc = np.where(Hc > 0, Bc * (1 - from_c / Hc), 0)
            Hi = Hi - from_i
            Hc = Hc - from_c
            proceeds = (sell * (1 - tc)).sum(1)
            tax = TAX * np.maximum((gi + gc).sum(1), 0)
            tax_paid += tax
            cash = proceeds - tax
            need = np.maximum(tgt - (Hi + Hc), 0)
            share = need / np.maximum(need.sum(1, keepdims=True), 1e-12)
            buy = share * cash[:, None]
            Hc += buy * (1 - tc)
            Bc += buy
        if contrib > 0:
            if method == "self_balance":
                H = Hi + Hc
                tgt = (H.sum(1, keepdims=True) + contrib) * w
                deficit = np.maximum(tgt - H, 0)
                tot = deficit.sum(1, keepdims=True)
                a = np.where(tot >= contrib, deficit * contrib / np.maximum(tot, 1e-12), deficit + (contrib - tot) * w)
            else:
                a = np.tile(contrib * w, (n, 1))
            Hc += a * (1 - tc)
            Bc += a
        V[:, t] = (Hi + Hc).sum(1)
        dep[t] = dep[t - 1] + contrib
    H = Hi + Hc
    liq = (H * (1 - tc)).sum(1)
    hold = T if tax_horizon is None else tax_horizon
    gain_c = (Hc * (1 - tc) - Bc).sum(1)
    gain_i = (Hi * (1 - tc) - Bi).sum(1)
    taxable = gain_c + (gain_i if hold < 24 else 0.0)                   # initial lot exempt after 2 years
    after_tax = liq - TAX * np.maximum(taxable, 0)
    drift = np.abs(H / H.sum(1, keepdims=True) - w).sum(1) / 2          # share of the pie off target at the end
    return {"V": V, "deposits": dep, "liq": liq, "after_tax": after_tax, "tax_paid_rebal": tax_paid,
            "drift": drift}


def summary(final: np.ndarray, deposits: float, V: np.ndarray | None = None, thresholds=(10_000, 12_500, 15_000, 20_000)) -> dict:
    out = {
        "deposits": deposits, "median": float(np.median(final)), "mean": float(final.mean()),
        "p5": float(np.percentile(final, 5)), "p25": float(np.percentile(final, 25)),
        "p75": float(np.percentile(final, 75)), "p95": float(np.percentile(final, 95)),
        "p_profit": float((final > deposits).mean()),
        "p_double_money": float((final >= 2 * deposits).mean()),
        "p_loss20": float((final <= 0.8 * deposits).mean()), "p_loss40": float((final <= 0.6 * deposits).mean()),
        "p_loss60": float((final <= 0.4 * deposits).mean()),
        "median_profit": float(np.median(final) - deposits),
    }
    for th in thresholds:
        out[f"p_ge_{th}"] = float((final >= th).mean())
    if V is not None:
        peak = np.maximum.accumulate(V, axis=1)
        mdd = (V / peak - 1).min(axis=1)
        out["median_path_mdd"] = float(np.median(mdd))
        out["p_path_dd30"] = float((mdd <= -0.30).mean())
    return out


def required_return(initial: float, contrib: float, months: int, target: float) -> float:
    """Annual compound return needed for `initial` now plus `contrib` at the end of each month to reach target."""
    lo, hi = -0.99, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        g = (1 + mid) ** (1 / 12)
        v = initial * g ** months + sum(contrib * g ** (months - m) for m in range(1, months + 1))
        lo, hi = (mid, hi) if v < target else (lo, mid)
    return (lo + hi) / 2


# ------------------------------------------------------------------------------------------------- rules

def portfolio_gross(R: np.ndarray, cols, port: dict) -> np.ndarray:
    """Monthly gross return of the pie with monthly rebalancing (paths, months) - used by timing rules."""
    j = [cols.index(k) for k in port]
    w = np.array([port[k] for k in port])
    return (np.exp(R[:, :, j]) * w).sum(2)


def apply_rule(Gp: np.ndarray, Gc: np.ndarray, rule: str, initial=5000.0, warm: np.ndarray | None = None) -> dict:
    """Exit / de-risking rules on a portfolio gross-return path Gp and the euro-cash path Gc.

    rules: hold; profit_take50 (at +50% move half the gain to cash); lock_target (at EUR 10,000 move all to
    cash); trail20 (after a 20% fall from the peak move to cash; buy back when the pie's own index recovers
    above its 10-month average); sma10 (hold only while the index is above its 10-month average, using a
    10-month warm-up history `warm`); glide18 (from month 18 move 1/6 to cash each month); dd_buy (keep 20% in
    cash and buy in after a 20% fall). Switching costs 0.1% and, when it realises gains, 12% tax on them.
    """
    n, T = Gp.shape
    risky = np.full(n, initial)
    cash = np.zeros(n)
    basis = np.full(n, initial)
    invested = np.ones(n, bool)
    idx_hist = [np.ones(n)] if warm is None else list(warm.T)
    level = idx_hist[-1].copy()
    peak = np.full(n, initial)
    taxes = np.zeros(n)
    if rule == "dd_buy":
        cash[:] = 0.2 * initial
        risky[:] = 0.8 * initial
        basis[:] = 0.8 * initial
        bought = np.zeros(n, bool)
    V = np.empty((n, T + 1))
    V[:, 0] = initial
    cost = 0.001

    def sell(mask, frac):
        nonlocal risky, cash, basis, taxes
        amt = risky * frac * mask
        g = amt - basis * frac * mask
        tx = TAX * np.maximum(g, 0)
        taxes += tx
        basis = basis - basis * frac * mask
        risky = risky - amt
        cash = cash + amt * (1 - cost) - tx

    def buy(mask, frac=1.0):
        nonlocal risky, cash, basis
        amt = cash * frac * mask
        risky = risky + amt * (1 - cost)
        basis = basis + amt
        cash = cash - amt

    for t in range(T):
        risky = risky * Gp[:, t]
        cash = cash * Gc[:, t]
        level = level * Gp[:, t]
        idx_hist.append(level.copy())
        v = risky + cash
        peak = np.maximum(peak, v)
        sma = np.mean(np.array(idx_hist[-10:]), axis=0) if len(idx_hist) >= 10 else level
        m = t + 1
        if rule == "profit_take50":
            trig = invested & (v >= 1.5 * initial)
            if trig.any():
                frac = np.where(trig, np.minimum((v - initial) / 2 / np.maximum(risky, 1e-9), 1), 0)
                sell(trig, frac)
                invested = invested & ~trig
        elif rule == "lock_target":
            trig = invested & (v >= 10_000)
            sell(trig, 1.0)
            invested = invested & ~trig
        elif rule == "trail20":
            out = invested & (v <= 0.8 * peak)
            sell(out, 1.0)
            back = ~invested & (level > sma)
            invested = (invested & ~out) | back
            buy(back)
            peak = np.where(back, risky + cash, peak)
        elif rule == "sma10":
            out = invested & (level < sma)
            back = ~invested & (level >= sma)
            sell(out, 1.0)
            buy(back)
            invested = (invested & ~out) | back
        elif rule == "glide18" and m >= 18:
            left = T - m + 1
            sell(np.ones(n, bool), np.full(n, 1.0 / max(left, 1)))
        elif rule == "dd_buy":
            trig = ~bought & (v <= 0.8 * peak)
            buy(trig)
            bought = bought | trig
        V[:, m] = risky + cash
    return {"V": V, "final": V[:, -1], "taxes": taxes}


def entry_plan(Gp: np.ndarray, Gc: np.ndarray, plan: str, initial=5000.0, dd_from_high: np.ndarray | None = None) -> np.ndarray:
    """Final value after T months of a lump sum vs staged entries; money waiting earns euro cash.

    plans: lump; dca3 / dca6 (equal parts at months 0..k-1); pullback10 (invest everything once the pie is 10%
    below its running high, else at month 6; `dd_from_high` gives the drawdown already in place at month 0);
    reserve20 (80% now, 20% after a 20% fall from the running high, else kept in cash).
    """
    n, T = Gp.shape
    risky = np.zeros(n)
    cash = np.full(n, initial)
    level = np.ones(n)
    high = np.ones(n) if dd_from_high is None else 1.0 / (1.0 + dd_from_high)
    done = np.zeros(n, bool)

    def invest(mask, amt):
        nonlocal risky, cash
        a = np.where(mask, np.minimum(amt, cash), 0.0)
        risky = risky + a * (1 - 0.001)
        cash = cash - a

    if plan == "lump":
        invest(np.ones(n, bool), cash.copy())
    elif plan == "reserve20":
        invest(np.ones(n, bool), 0.8 * initial)
    for t in range(T):
        if plan.startswith("dca"):
            k = int(plan[3:])
            if t < k:
                invest(np.ones(n, bool), np.full(n, initial / k))
        elif plan == "pullback10" and t <= 6:
            trig = ~done & ((level / high - 1 <= -0.10) | (t == 6))
            invest(trig, cash.copy())
            done |= trig
        elif plan == "reserve20":
            trig = ~done & (level / high - 1 <= -0.20)
            invest(trig, cash.copy())
            done |= trig
        risky = risky * Gp[:, t]
        cash = cash * Gc[:, t]
        level = level * Gp[:, t]
        high = np.maximum(high, level)
    return risky + cash


def lognormal_tradeoff(mu_annual=0.07, years=2.0, sigmas=np.arange(0.0, 0.61, 0.05)):
    """P(double) and P(lose >= 40%) for a lognormal wealth with compound growth mu and volatility sigma."""
    from math import erf, log, sqrt

    def cdf(x):
        return 0.5 * (1 + erf(x / sqrt(2)))
    rows = []
    m = log(1 + mu_annual) * years
    for s in sigmas:
        sd = s * sqrt(years)
        if sd == 0:
            rows.append({"sigma": float(s), "p_double": float(m >= log(2)), "p_loss40": 0.0})
            continue
        rows.append({"sigma": float(s), "p_double": 1 - cdf((log(2) - m) / sd), "p_loss40": cdf((log(0.6) - m) / sd)})
    return rows
