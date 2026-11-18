"""Phase 2 portfolio engine: every purchase is its own tax lot.

Each deposit (the initial sum and every monthly top-up) opens a "vintage": a lot per holding with its own
purchase month and cost basis. Croatian rules (Zakon o porezu na dohodak, cl. 67 st. 8 and cl. 70 st. 5):
  * a lot sold more than two years after purchase is tax-free;
  * sales match the oldest lots first (FIFO);
  * gains and losses on taxable lots in the same calendar year offset each other; tax is 12% of the net gain.
A sale at month s treats a lot bought at month v as exempt if s - v >= 24 (the sale is assumed to happen just
after the two-year anniversary, e.g. on day 731).

Rebalancing never sells unless `sell_rebalance_months` is given; by default new money is split by target
weight ("target", Trading 212 AutoInvest) or underweight-first ("self_balance").
"""
from __future__ import annotations

import numpy as np

from sim import TAX, trade_cost


def deposit_schedule(horizon: int, contrib: float, timing: str = "end", n_deposits: int | None = None) -> np.ndarray:
    """Amount deposited at each month 0..horizon (excluding the initial lump sum).

    timing "end": top-ups at the end of months 1..horizon (24 top-ups over 24 months; the last one earns
    nothing). "start": top-ups at the start of months 2..horizon+1, i.e. at the end of months 1..horizon-1
    plus none at the horizon (23 top-ups over 24 months). `n_deposits` caps the count.
    """
    d = np.zeros(horizon + 1)
    months = range(1, horizon + 1) if timing == "end" else range(1, horizon)
    for k, m in enumerate(months):
        if n_deposits is not None and k >= n_deposits:
            break
        d[m] = contrib
    return d


def simulate_lots(R: np.ndarray, cols, port: dict, initial=5000.0, contrib=0.0, horizon: int | None = None,
                  method="target", timing="end", n_deposits=None, sell_rebalance_months=(),
                  deposits: np.ndarray | None = None):
    """Simulate a pie with per-vintage tax lots.

    R: (paths, months, sleeves) monthly log returns. Returns monthly account values V (paths, T+1), cumulative
    deposits, liquidation value after selling costs, after-tax value if everything is sold at the horizon, the
    value of lots already tax-exempt at that point, and taxes paid on rebalancing sales.
    """
    T = R.shape[1] if horizon is None else horizon
    n = R.shape[0]
    keys = list(port)
    j = [cols.index(k) for k in keys]
    w = np.array([port[k] for k in keys])
    J = len(keys)
    G = np.exp(R[:, :T, j])
    tc = np.array([trade_cost(k) for k in keys])
    dep = deposit_schedule(T, contrib, timing, n_deposits) if deposits is None else np.asarray(deposits, float)
    dep = dep.copy()
    dep[0] = initial
    H = np.zeros((n, T + 1, J))                    # value of each vintage x holding
    B = np.zeros((n, T + 1, J))                    # cost basis of each vintage x holding
    H[:, 0] = initial * w * (1 - tc)
    B[:, 0] = initial * w
    V = np.empty((n, T + 1))
    V[:, 0] = H[:, 0].sum(1)
    tax_rebal = np.zeros(n)
    for t in range(1, T + 1):
        H[:, :t] *= G[:, t - 1][:, None, :]
        if t in sell_rebalance_months:
            tot = H[:, :t].sum(1)                                         # per holding
            tgt = tot.sum(1, keepdims=True) * w
            sell = np.maximum(tot - tgt, 0)                               # euros to sell per holding
            gain = np.zeros(n)
            for v in range(t):                                            # FIFO: oldest vintage first
                take = np.minimum(sell, H[:, v])
                with np.errstate(invalid="ignore", divide="ignore"):
                    frac = np.where(H[:, v] > 0, take / H[:, v], 0.0)
                taxable = (t - v) < 24
                if taxable:
                    gain += (take * (1 - tc) - B[:, v] * frac).sum(1)
                B[:, v] *= 1 - frac
                H[:, v] -= take
                sell = sell - take
            proceeds = (np.maximum(tot - tgt, 0) * (1 - tc)).sum(1)
            tax = TAX * np.maximum(gain, 0)
            tax_rebal += tax
            cash = proceeds - tax
            need = np.maximum(tgt - H[:, :t].sum(1), 0)
            share = need / np.maximum(need.sum(1, keepdims=True), 1e-12)
            buy = share * cash[:, None]
            H[:, t] += buy * (1 - tc)
            B[:, t] += buy
        c = dep[t]
        if c > 0:
            if method == "self_balance":
                tot = H[:, :t + 1].sum(1)
                tgt = (tot.sum(1, keepdims=True) + c) * w
                deficit = np.maximum(tgt - tot, 0)
                s = deficit.sum(1, keepdims=True)
                a = np.where(s >= c, deficit * c / np.maximum(s, 1e-12), deficit + (c - s) * w)
            else:
                a = np.tile(c * w, (n, 1))
            H[:, t] += a * (1 - tc)
            B[:, t] += a
        V[:, t] = H[:, :t + 1].sum((1, 2))
    net = H * (1 - tc)                                                    # after selling costs
    liq = net.sum((1, 2))
    exempt = (T - np.arange(T + 1)) >= 24                                 # lot age at the sale, in months
    gain_taxable = (net[:, ~exempt] - B[:, ~exempt]).sum((1, 2))
    tax = TAX * np.maximum(gain_taxable, 0)
    tot = H[:, :T + 1].sum(1)
    drift = np.abs(tot / tot.sum(1, keepdims=True) - w).sum(1) / 2
    return {"V": V, "deposits": np.cumsum(dep), "liq": liq, "after_tax": liq - tax, "tax": tax,
            "exempt_value": net[:, exempt].sum((1, 2)), "tax_rebal": tax_rebal, "drift": drift}


def grid_matrices(R: np.ndarray, cols, sleeves, initial=5000.0, contrib=0.0, horizon=24, timing="end"):
    """Per-sleeve terminal euro value of putting ALL money in one sleeve, for target-split buy-and-hold pies.

    With target-split deposits and no selling, the liquidation value of a pie with weights w is exactly
    sum_i w_i * A[:, i], so millions of pies can be scored with one matrix product.
    """
    j = [cols.index(s) for s in sleeves]
    lg = R[:, :horizon, j]
    cum_from = np.flip(np.cumsum(np.flip(lg, 1), 1), 1)                   # log growth from month m to horizon
    tc = np.array([trade_cost(s) for s in sleeves])
    dep = deposit_schedule(horizon, contrib, timing)
    A = initial * np.exp(cum_from[:, 0])
    for m in range(1, horizon + 1):
        if dep[m] > 0:
            A = A + dep[m] * (np.exp(cum_from[:, m]) if m < horizon else 1.0)
    return A * (1 - tc) ** 2, float(initial + dep.sum())


def summarize(final: np.ndarray, deposits: float, V: np.ndarray | None = None, after_tax: np.ndarray | None = None,
              deflator: float = 1.0, thresholds=(10_000, 12_500, 15_000, 20_000)) -> dict:
    """Outcome statistics. `deflator` = price level at the horizon (1.0 = nominal) for real figures."""
    f = final / deflator
    out = {"deposits": deposits, "median": float(np.median(f)), "mean": float(f.mean()),
           "p5": float(np.percentile(f, 5)), "p95": float(np.percentile(f, 95)),
           "median_profit": float(np.median(f) - deposits), "mean_profit": float(f.mean() - deposits),
           "p_profit": float((f > deposits).mean()), "p_double_invested": float((f >= 2 * deposits).mean())}
    for k in (10, 20, 30, 40, 50):
        out[f"p_loss{k}"] = float((f <= (1 - k / 100) * deposits).mean())
    for th in thresholds:
        out[f"p_ge_{th}"] = float((f >= th).mean())
    if after_tax is not None:
        a = after_tax / deflator
        out["after_tax_median"] = float(np.median(a))
        out["after_tax_mean_profit"] = float(a.mean() - deposits)
        out["after_tax_p_ge_10000"] = float((a >= 10_000).mean())
    if V is not None:
        peak = np.maximum.accumulate(V, axis=1)
        mdd = (V / peak - 1).min(axis=1)
        out["p_path_dd30"] = float((mdd <= -0.30).mean())
    return out


def binom_ci(p: float, n: int, z: float = 1.96):
    """Wilson interval for a simulated probability (Monte Carlo noise only, not model uncertainty)."""
    if n == 0:
        return (np.nan, np.nan)
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))
