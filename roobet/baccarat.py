"""Punto Banco (baccarat) outcome probabilities by exact enumeration of an 8-deck shoe.

Roobet offers baccarat only as third-party live tables (casino category "baccarat"), whose
payouts are set by each provider. Modelled here: the standard drawing rules and the usual
commission table (Banker pays 0.95:1, Player 1:1, Tie 8:1; Banker/Player push on a tie).
The probabilities are pure combinatorics of the drawing rules; the payouts are an assumption.
"""
from __future__ import annotations

from functools import lru_cache


def _banker_draws(banker: int, player_third: int | None) -> bool:
    if player_third is None:                 # player stood: banker draws on 0-5
        return banker <= 5
    x = player_third
    if banker <= 2:
        return True
    if banker == 3:
        return x != 8
    if banker == 4:
        return 2 <= x <= 7
    if banker == 5:
        return 4 <= x <= 7
    if banker == 6:
        return x in (6, 7)
    return False


@lru_cache(maxsize=None)
def outcome_probs(decks: int = 8) -> dict:
    """P(Banker wins), P(Player wins), P(Tie) for a freshly shuffled `decks`-deck shoe."""
    counts = [16 * decks] + [4 * decks] * 9     # card values 0 (10/J/Q/K) and 1..9
    total = 52 * decks
    res = {"banker": 0.0, "player": 0.0, "tie": 0.0}

    def draw(cnt, n):
        for v in range(10):
            if cnt[v]:
                p = cnt[v] / n
                cnt[v] -= 1
                yield v, p
                cnt[v] += 1

    cnt = list(counts)
    n = total
    for p1, a in draw(cnt, n):
        for b1, b in draw(cnt, n - 1):
            for p2, c in draw(cnt, n - 2):
                for b2, d in draw(cnt, n - 3):
                    w4 = a * b * c * d
                    pt, bt = (p1 + p2) % 10, (b1 + b2) % 10
                    if pt >= 8 or bt >= 8:
                        _score(res, pt, bt, w4)
                        continue
                    if pt <= 5:
                        for p3, e in draw(cnt, n - 4):
                            pt3 = (pt + p3) % 10
                            if _banker_draws(bt, p3):
                                for b3, f in draw(cnt, n - 5):
                                    _score(res, pt3, (bt + b3) % 10, w4 * e * f)
                            else:
                                _score(res, pt3, bt, w4 * e)
                    else:
                        if _banker_draws(bt, None):
                            for b3, f in draw(cnt, n - 4):
                                _score(res, pt, (bt + b3) % 10, w4 * f)
                        else:
                            _score(res, pt, bt, w4)
    return res


def _score(res, pt, bt, w):
    if bt > pt:
        res["banker"] += w
    elif pt > bt:
        res["player"] += w
    else:
        res["tie"] += w


def bets(decks: int = 8):
    """(name, nets, probs, max loss per unit) for the three main bets."""
    q = outcome_probs(decks)
    B, P, T = q["banker"], q["player"], q["tie"]
    return [
        ("baccarat:banker", (0.95, 0.0, -1.0), (B, T, P), 1.0),
        ("baccarat:player", (1.0, 0.0, -1.0), (P, T, B), 1.0),
        ("baccarat:tie", (8.0, -1.0), (T, 1 - T), 1.0),
    ]
