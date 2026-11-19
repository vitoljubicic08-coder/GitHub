"""Roobet blackjack under EV-optimal basic strategy: exact outcome distributions.

Rules from Roobet's blackjack verifier (2026-11-16): 8-deck shoe shuffled from the round
hash every round (no card counting is possible), dealer stands on all 17s, blackjack pays
3:2, insurance pays 2:1 (never taken here), double and split exist, a split hand's 21 is
not a natural, a dealer natural beats every non-natural hand.

Not stated by the verifier, so modelled both ways or assumed:
  * whether the dealer peeks for blackjack before the player acts ("peek") or the player
    loses doubled/split stakes to a dealer natural found at the end ("enhc");
  * one split only (no re-split), double after split allowed, split aces get one card.

The shoe is modelled as infinite (8 decks reshuffled each round is within ~0.05% of it).
The result of one round is a distribution over the net change per unit of the initial
stake on a half-unit grid from -4 to +4 (two split hands, both doubled, both lost = -4).
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

CARDS = np.array([2, 3, 4, 5, 6, 7, 8, 9, 10, 11])          # 11 = ace
PCARD = np.array([1, 1, 1, 1, 1, 1, 1, 1, 4, 1]) / 13.0
NGRID = 17                                                   # net = (i - 8) / 2
CATS = ("BJ", 17, 18, 19, 20, 21, "bust")


def idx(net: float) -> int:
    return int(round(net * 2)) + 8


def _add(total: int, soft: bool, card: int) -> tuple[int, bool]:
    if card == 11:
        if total + 11 <= 21:
            return total + 11, True
        total += 1
    else:
        total += card
    if total > 21 and soft:
        return total - 10, False
    return total, soft


@lru_cache(maxsize=None)
def _dealer_from(total: int, soft: bool) -> tuple:
    """Dealer final distribution over (17..21, bust) from a hand with >= 2 cards, S17."""
    if total > 21:
        return (0, 0, 0, 0, 0, 1.0)
    if total >= 17:
        out = [0.0] * 6
        out[total - 17] = 1.0
        return tuple(out)
    out = np.zeros(6)
    for c, p in zip(CARDS, PCARD):
        out += p * np.array(_dealer_from(*_add(total, soft, int(c))))
    return tuple(out)


def dealer_dist(up: int) -> np.ndarray:
    """P(BJ, 17, 18, 19, 20, 21, bust) for a dealer upcard, unconditional (hole card random)."""
    out = np.zeros(7)
    t0, s0 = _add(0, False, up)
    for c, p in zip(CARDS, PCARD):
        t, s = _add(t0, s0, int(c))
        if t == 21:                       # two-card 21 = natural
            out[0] += p
        else:
            out[1:] += p * np.array(_dealer_from(t, s))
    return out


class Blackjack:
    """Basic strategy and outcome distribution for one rule set and one affordability regime."""

    def __init__(self, variant: str = "peek", double: bool = True, split: bool = True, das: bool = True):
        if variant not in ("peek", "enhc"):
            raise ValueError(variant)
        self.variant, self.double, self.split, self.das = variant, double, split, das

    # ---- per upcard -------------------------------------------------------------------
    def _setup(self, up: int):
        d = dealer_dist(up)
        self.p_bj = d[0]
        if self.variant == "peek":
            dd = d.copy()
            dd[0] = 0.0
            self.D = dd / dd.sum()
        else:
            self.D = d
        self._stand_cache = {}
        self._best_cache = {}

    def _stand_dist(self, total: int, mult: int = 1) -> np.ndarray:
        """Per dealer category: net result of standing on `total` (non-natural) with `mult` units."""
        key = (total, mult)
        if key in self._stand_cache:
            return self._stand_cache[key]
        r = np.zeros(7)
        if total > 21:
            r[:] = -mult
        else:
            r[0] = -mult                                            # dealer natural
            for k, dt in enumerate((17, 18, 19, 20, 21), start=1):
                r[k] = mult * np.sign(total - dt)
            r[6] = mult                                             # dealer bust
        self._stand_cache[key] = r
        return r

    def _onehot(self, values: np.ndarray) -> np.ndarray:
        """(7,) per-category net values -> (7, NGRID) distributions."""
        out = np.zeros((7, NGRID))
        for k, v in enumerate(values):
            out[k, idx(v)] = 1.0
        return out

    def _ev(self, dist: np.ndarray) -> float:
        nets = (np.arange(NGRID) - 8) / 2
        return float(self.D @ (dist @ nets))

    def _play(self, total: int, soft: bool) -> np.ndarray:
        """Best of stand/hit after the first decision (no double): (7, NGRID) distribution."""
        key = (total, soft)
        if key in self._best_cache:
            return self._best_cache[key]
        stand = self._onehot(self._stand_dist(total))
        if total >= 21:
            self._best_cache[key] = stand
            return stand
        hit = self._hit(total, soft, lambda t, s: self._play(t, s))
        best = hit if self._ev(hit) > self._ev(stand) else stand
        self._best_cache[key] = best
        return best

    def _hit(self, total, soft, cont):
        out = np.zeros((7, NGRID))
        for c, p in zip(CARDS, PCARD):
            t, s = _add(total, soft, int(c))
            out += p * (self._onehot(np.full(7, -1.0)) if t > 21 else cont(t, s))
        return out

    def _double(self, total, soft):
        out = np.zeros((7, NGRID))
        for c, p in zip(CARDS, PCARD):
            t, s = _add(total, soft, int(c))
            out += p * self._onehot(self._stand_dist(t, 2))
        return out

    def _first(self, total, soft, can_double) -> tuple[np.ndarray, str]:
        opts = {"S": self._onehot(self._stand_dist(total))}
        if total < 21:
            opts["H"] = self._hit(total, soft, lambda t, s: self._play(t, s))
            if can_double:
                opts["D"] = self._double(total, soft)
        act = max(opts, key=lambda a: self._ev(opts[a]))
        return opts[act], act

    def _split_hand(self, card: int) -> np.ndarray:
        """Distribution of one hand started from a split card (per dealer category)."""
        out = np.zeros((7, NGRID))
        t0, s0 = _add(0, False, card)
        for c, p in zip(CARDS, PCARD):
            t, s = _add(t0, s0, int(c))
            if card == 11:                               # split aces: one card, stand
                d = self._onehot(self._stand_dist(t))
            else:
                d, _ = self._first(t, s, self.double and self.das)
            out += p * d
        return out

    @staticmethod
    def _convolve(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        out = np.zeros((7, NGRID))
        for k in range(7):
            c = np.convolve(a[k], b[k])                  # nets add; grid offset 8+8 -> 16
            out[k] = c[8:8 + NGRID]
            if c[:8].sum() > 1e-12 or c[8 + NGRID:].sum() > 1e-12:
                raise RuntimeError("net outside grid")
        return out

    # ---- whole round --------------------------------------------------------------------
    def round_distribution(self) -> tuple[np.ndarray, dict]:
        """Net result distribution of one round (NGRID,) and the strategy table used."""
        total = np.zeros(NGRID)
        strategy = {}
        for up, pu in zip(CARDS, PCARD):
            up = int(up)
            self._setup(up)
            per_cat = np.zeros((7, NGRID))
            for c1, p1 in zip(CARDS, PCARD):
                for c2, p2 in zip(CARDS, PCARD):
                    c1i, c2i = int(c1), int(c2)
                    t, s = _add(*_add(0, False, c1i), c2i)
                    if t == 21:                                   # player natural
                        nat = np.zeros((7, NGRID))
                        nat[:, idx(1.5)] = 1.0
                        nat[0, :] = 0.0
                        nat[0, idx(0)] = 1.0                      # push against dealer natural
                        per_cat += p1 * p2 * nat
                        continue
                    d, act = self._first(t, s, self.double)
                    if self.split and c1i == c2i:
                        sp = self._convolve(self._split_hand(c1i), self._split_hand(c1i))
                        if self._ev(sp) > self._ev(d):
                            d, act = sp, "P"
                    strategy[(up, min(c1i, c2i), max(c1i, c2i))] = act
                    per_cat += p1 * p2 * d
            dist_up = self.D @ per_cat
            if self.variant == "peek":
                p_nat_player = 2 * PCARD[8] * PCARD[9]
                bj = np.zeros(NGRID)
                bj[idx(-1)] = 1 - p_nat_player
                bj[idx(0)] = p_nat_player
                dist_up = self.p_bj * bj + (1 - self.p_bj) * dist_up
            total += pu * dist_up
        return total, strategy


def nets() -> np.ndarray:
    return (np.arange(NGRID) - 8) / 2


def regimes(variant: str = "peek") -> dict[str, np.ndarray]:
    """Outcome distributions for the three bankroll regimes used in the challenge."""
    return {
        "full": Blackjack(variant, True, True, True).round_distribution()[0],     # stake <= B/4
        "double": Blackjack(variant, True, True, False).round_distribution()[0],  # stake <= B/2
        "none": Blackjack(variant, False, False, False).round_distribution()[0],  # all-in
    }


def ev(dist: np.ndarray) -> float:
    return float(dist @ nets())
