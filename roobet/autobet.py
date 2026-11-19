"""Roobet Auto Bet as a strategy the engine can simulate and solve exactly.

Settings, from Roobet's help article https://help.roobet.com/en/articles/15262440-autobet
(May 2026):
  * Bet Amount, and the game's own setting (Dice win chance, Limbo target, Crash auto-cashout,
    Mines/Towers tiles chosen in advance); the setting does not change during a run;
  * Number of Bets (blank = until stopped);
  * Stop On Profit / Stop On Loss, both measured from the balance when the run started;
  * On Win and On Loss: "reset" to the base amount, or "increase by" a percentage of the
    *current* bet (compounding: $1 +20% -> $1.20 -> $1.44).
Not available: stakes as a share of the balance, changing the multiplier mid-run, or rules
that depend on anything but the last result.

Modelling choices (not documented by Roobet, so tested both ways where they matter):
  * the bet placed is the compounded amount rounded to the cent (half up by default;
    `rounding="floor"` / `"ceil"` for sensitivity);
  * if the next bet is larger than the balance, the run halts (insufficient balance) and the
    rest of the balance is kept; with `finish=` a policy table, the player instead finishes
    by hand with that policy (the manual "Auto Bet + finish" variant).
"""
from __future__ import annotations

import numpy as np

from engine import EPS, Strategy
from games import TARGET

CAP = 16000          # counters never get near this before the stake outgrows the bankroll


class AutoBet(Strategy):
    exact_stakes = True
    needs_B = True

    def __init__(self, base, mult, on_win="reset", on_loss="reset", win_pct=0.0, loss_pct=0.0,
                 stop_profit=None, stop_loss=None, start=2000, rounding="half_up", finish=None,
                 name=None, family="autobet"):
        if on_win not in ("reset", "increase") or on_loss not in ("reset", "increase"):
            raise ValueError("on_win/on_loss must be 'reset' or 'increase'")
        if base > start:
            raise ValueError("base bet larger than the starting balance")
        super().__init__(name or self._label(base, mult, on_win, on_loss, win_pct, loss_pct), family,
                         ("i", "j", "mode"))
        self.base, self.mult = int(base), float(mult)
        self.on_win, self.on_loss = on_win, on_loss
        self.wp, self.lp = float(win_pct), float(loss_pct)
        self.stop_profit, self.stop_loss = stop_profit, stop_loss
        self.start, self.rounding = start, rounding
        self.finish = None if finish is None else np.asarray(finish, np.int64)

    @staticmethod
    def _label(base, mult, on_win, on_loss, wp, lp):
        w = "reset" if on_win == "reset" else f"+{wp*100:g}%"
        l = "reset" if on_loss == "reset" else f"+{lp*100:g}%"
        return f"Auto Bet ${base/100:g} at {mult:.4g}x, win {w}, loss {l}"

    def stake(self, st):
        x = self.base * (1.0 + self.wp) ** st["i"] * (1.0 + self.lp) ** st["j"]
        if self.rounding == "floor":
            s = np.floor(x + EPS)
        elif self.rounding == "ceil":
            s = np.ceil(x - EPS)
        else:
            s = np.floor(x + 0.5 + EPS)
        return np.maximum(s, 1).astype(np.int64)

    def _finishing(self, B, st, s):
        if self.finish is None:
            return np.zeros(len(B), bool)
        return (st["mode"] == 1) | (s > B)

    def act(self, B, st, rng=None):
        s = self.stake(st)
        m = np.full(len(B), self.mult)
        fin = self._finishing(B, st, s)
        if fin.any():
            fs = np.maximum(self.finish[np.minimum(B, len(self.finish) - 1)], 1)
            s = np.where(fin, fs, s)
            m = np.where(fin, (TARGET - B + fs) / fs, m)
        return s, m

    def update_b(self, st, win, B):
        s = self.stake(st)
        fin = self._finishing(B, st, s)
        i, j = st["i"], st["j"]
        zero = np.zeros_like(i)
        iw, jw = (i + 1, j) if self.on_win == "increase" else (zero, zero)
        il, jl = (i, j + 1) if self.on_loss == "increase" else (zero, zero)
        ni = np.minimum(np.where(win, iw, il), CAP)
        nj = np.minimum(np.where(win, jw, jl), CAP)
        return {"i": np.where(fin, i, ni), "j": np.where(fin, j, nj), "mode": np.where(fin, 1, st["mode"])}

    def stop(self, B, st):
        out = np.zeros(len(B), bool)
        if self.stop_profit is not None:
            out |= B >= self.start + self.stop_profit
        if self.stop_loss is not None:
            out |= B <= self.start - self.stop_loss
        if self.finish is None:
            out |= self.stake(st) > B          # Auto Bet halts: next bet exceeds the balance
        return out


def dice_chance_for(mult, rtp=0.99):
    """Largest Dice win chance (0.01 steps) whose multiplier 100*rtp/chance is >= mult."""
    return np.floor(100.0 * rtp / mult * 100 + EPS) / 100


def _lands_on_target(base, m, pct, start, rounding):
    probe = AutoBet(base, m, on_loss="increase", loss_pct=pct, start=start, rounding=rounding)
    B, j = start, 0
    while True:
        s = int(probe.stake({"i": np.array([0]), "j": np.array([j])})[0])
        if s > B:
            return True
        if B - s + np.floor(s * m + EPS) < TARGET:
            return False
        B -= s
        j += 1


def geometric(chance, start=2000, rtp=0.99, pct_decimals=2, rounding="half_up", finish=None, name=None):
    """"Recover-and-reach" Auto Bet on Dice: every win lands on $100.

    At multiplier m a stake s0 with s0*(m-1) >= $100 - start wins the target on the first bet.
    Raising the bet by 1/(m-1) after each loss keeps that true after any run of losses
    (s_k = s0 * (m/(m-1))^k), and the run halts when the next bet no longer fits.
    The percentage is rounded UP to `pct_decimals` decimals of a percent, as typed in the form.
    """
    m = 100.0 * rtp / chance
    need = TARGET - start
    q = 10 ** pct_decimals
    pct = np.ceil(100.0 / (m - 1) * q - EPS) / q / 100.0
    base = int(np.ceil(need / (m - 1) - EPS))
    # Cent rounding can leave a raised bet a cent short, and at m x a cent of stake is
    # (m - 1) cents of payout, so a win would land just under $100. Take the smallest base
    # for which every win along the losing run still lands on >= $100.
    while not _lands_on_target(base, m, pct, start, rounding):
        base += 1
        if base > start:
            raise ValueError("no base bet keeps every win on target")
    label = name or f"Auto Bet Dice {chance:g}% ({m:.4g}x), ${base/100:.2f}, loss +{pct*100:g}%, stop profit ${need/100:g}"
    return AutoBet(base, m, on_win="reset", on_loss="increase", loss_pct=pct, stop_profit=need,
                   start=start, rounding=rounding, finish=finish, name=label, family="autobet-geometric")
