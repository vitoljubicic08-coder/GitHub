"""Roobet house-game payout models, each traced to a source.

Money is in integer cents everywhere. A *bet type* is a discrete outcome distribution
of the net change per unit staked: the bankroll moves from B to B + floor(stake * net_k)
with probability p_k. A plain win at gross multiplier m has net m - 1; a loss has net -1.

Sources (fetched 2026-11-19; see SOURCES below):
  [V] Roobet's own provably-fair verifier code, linked per game from roobet.com/fair
      (codesandbox sandboxes; crash updated 2026-09-19, limbo/dice/wheel/hilo/towers/
      blackjack updated Sep-Nov 2026). These give the exact outcome derivations.
  [H] help.roobet.com articles ("Roobet House Games", "Triple Roo Jackpot", "Autobet").
  [P] Roobet Game Policy as quoted by search results (min bet $0.01, max $20,000 on
      company games, Plinko max $10,000, max win $500,000; Coinflip 4% fee).
  [3] Third-party only (mesmeric.games reviews); used where Roobet publishes no table,
      and flagged as unverified.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import comb

import numpy as np

TARGET = 10_000          # $100.00 in cents
START = 1_000            # $10.00 in cents
MIN_STAKE = 1            # $0.01  [P]

SOURCES = {
    "fair": "https://roobet.com/fair (links each verifier below)",
    "crash": "https://codesandbox.io/embed/crash-93kqwr",
    "roulette": "https://codesandbox.io/embed/roulette-yqqsfy",
    "dice": "https://codesandbox.io/p/sandbox/6wmyl3",
    "limbo": "https://codesandbox.io/p/sandbox/j4nfmz",
    "mines": "https://codesandbox.io/embed/mines-4xxw25",
    "towers": "https://codesandbox.io/p/sandbox/lzp8mn",
    "plinko": "https://codesandbox.io/embed/plinko-kkqkvy",
    "wheel": "https://codesandbox.io/p/sandbox/relaxed-heyrovsky-nrmykz",
    "hilo": "https://codesandbox.io/p/devbox/cjf4gr",
    "slide": "https://codesandbox.io/embed/slide-forked-gcy25k",
    "blackjack": "https://codesandbox.io/p/sandbox/kv44m9",
    "coinflip": "https://codesandbox.io/embed/coinflip-provably-fair-h367ys",
    "house_games_help": "https://help.roobet.com/en/articles/10261516-roobet-house-games",
    "triple_roo": "https://help.roobet.com/en/articles/12333430-triple-roo-jackpot",
    "towers_table": "https://mesmeric.games/game/roobet-towers-review/",
    "dice_review": "https://mesmeric.games/game/roobet-dice-review/",
    "mines_review": "https://mesmeric.games/game/roobet-mines-review/",
    "hr_blocklist": "https://porezna-uprava.gov.hr/hr/nedozvoljeno-obavljanje-gospodarske-aktivnosti-putem-interneta/3984",
}


@dataclass(frozen=True)
class BetType:
    """One way of placing a single wager: outcomes are net multipliers with probabilities."""
    name: str
    net: tuple[float, ...]
    prob: tuple[float, ...]
    verified: str = "V"            # V = verifier code, H = help centre, I = inferred, 3 = third party
    note: str = ""

    def __post_init__(self):
        if abs(sum(self.prob) - 1.0) > 1e-9:
            raise ValueError(f"{self.name}: probabilities sum to {sum(self.prob)}")
        if min(self.net) < -1 - 1e-12 and self.name.split(":")[0] != "blackjack":
            raise ValueError(f"{self.name}: a simple bet cannot lose more than the stake")

    @property
    def rtp(self) -> float:
        return 1.0 + float(np.dot(self.net, self.prob))

    @property
    def edge(self) -> float:
        return 1.0 - self.rtp

    @property
    def max_loss(self) -> float:
        """Largest loss per unit staked (1 for simple bets; up to 4 for blackjack splits+doubles)."""
        return -min(self.net)


def two_outcome(name, mult, p, verified="V", note="") -> BetType:
    return BetType(name, (mult - 1.0, -1.0), (p, 1.0 - p), verified, note)


# --------------------------------------------------------------------------- Dice
# [V] roll = floor(U*10^4)/10^2 on the grid 0.00..99.99 (10,000 equally likely values).
# The verifier does not state the payout. Roobet's in-game info (via [3]) lists
# max multiplier 9,900x at the minimum 0.01% win chance and min multiplier 1.01x,
# which is exactly multiplier = 99 / chance%  ->  RTP 99% (1% edge). A secondary
# claim of 98.6% RTP exists; the sensitivity runs cover 98.6% and 98%.
DICE_RTP = 0.99


def dice(chance_pct: float, rtp: float = DICE_RTP) -> BetType:
    """Win chance in percent with 2 decimals (0.01..98.00); multiplier = 100*rtp/chance."""
    c = round(chance_pct, 2)
    if not 0.01 <= c <= 98.0:
        raise ValueError("dice chance must be within 0.01..98.00")
    return two_outcome(f"dice:{c:.2f}%", 100.0 * rtp / c, c / 100.0, "I",
                       "roll grid verified; multiplier 99/chance inferred from 9,900x max")


def dice_for_multiplier(mult: float, rtp: float = DICE_RTP) -> BetType:
    """Largest dice chance (2 dp) whose multiplier is >= mult."""
    c = np.floor(100.0 * rtp / mult * 100 + 1e-9) / 100
    return dice(c, rtp)


# --------------------------------------------------------------------------- Limbo / Slide
# [V] limbo (modern): result = clamp(0.98/(1-U), 1, 1e6) truncated to 2 dp; win if result >= target.
# For a target t on the 0.01 grid, P(win) = 0.98/t exactly (truncation cannot cross a grid point).
# [V] slide: same curve with a 2% edge (shared rounds, 52-bit variate).
def limbo(target: float, rtp: float = 0.98) -> BetType:
    t = round(target, 2)
    if not 1.01 <= t <= 1_000_000:
        raise ValueError("limbo target must be within 1.01..1,000,000")
    return two_outcome(f"limbo:{t:.2f}x", t, rtp / t)


def slide(target: float) -> BetType:
    b = limbo(target)
    return BetType(b.name.replace("limbo", "slide"), b.net, b.prob, "V")


# --------------------------------------------------------------------------- Crash
# [V] crash: if HMAC hash divisible by parseInt(100/4)=25 -> instant crash at 1.00x (4%);
# else crash = floor((100e - h)/(e - h))/100 with h the first 52 bits. For a cash-out
# target t (2 dp, >= 1.01): P(crash >= t) = (24/25) * 99/(100t - 1).
def crash_p(target: float) -> float:
    t = round(target, 2)
    return 0.96 * 99.0 / (100.0 * t - 1.0)


def crash(target: float) -> BetType:
    t = round(target, 2)
    if t < 1.01:
        raise ValueError("crash auto-cashout must be >= 1.01")
    return two_outcome(f"crash:{t:.2f}x", t, crash_p(t))


# --------------------------------------------------------------------------- Roulette
# [V] result = (first 52 bits) mod 15: 0 -> green 14x; 7 or 8 -> "7x bait"; 1-6 red; 9-14 black.
# [H] the wheel shows 7 red, 7 black, 1 green and the two bait tiles sit next to green.
# Whether a red/black bet also wins on the adjacent bait tile is not stated; with it the
# red/black RTP is 2*7/15 = 93.33% (equal to green 14/15 and bait 14/15), without it 80%.
def roulette(kind: str, bait_counts_as_colour: bool = True) -> BetType:
    if kind == "green":
        return two_outcome("roulette:green", 14.0, 1 / 15)
    if kind == "bait":
        return two_outcome("roulette:bait", 7.0, 2 / 15)
    if kind in ("red", "black"):
        n = 7 if bait_counts_as_colour else 6
        return two_outcome(f"roulette:{kind}", 2.0, n / 15, "V" if not bait_counts_as_colour else "H",
                           "bait tile counted as colour" if bait_counts_as_colour else "verifier labels only")
    raise ValueError(kind)


# --------------------------------------------------------------------------- Wheel
# [V] house edge 2% on every difficulty (since 2026-09-18 for high): with probability 0.02
# the draw lands on a 0x segment, otherwise uniform over the segments of the tier.
WHEEL_TIERS = {
    "low": {10: [2, 1, 1, 1, 0] * 2},
    "medium": {10: [0, 2, 0, 1, 0, 2, 0, 2, 0, 3],
               50: [2, 0, 1, 0, 2, 0, 2, 0, 3, 0, 1, 0, 2, 0, 2, 0, 3, 0, 1, 0, 2, 0, 2, 0, 2,
                    0, 1, 0, 2, 0, 2, 0, 3, 0, 1, 0, 2, 0, 2, 0, 2, 0, 1, 0, 5, 0, 2, 0, 2, 0]},
    "high": {n: [0] * (n - 1) + [n] for n in (10, 20, 30, 40, 50)},
}


def wheel(difficulty: str, segments: int, edge: float = 0.02) -> BetType:
    tier = WHEEL_TIERS[difficulty][segments]
    probs: dict[float, float] = {}
    for m in tier:
        probs[m] = probs.get(m, 0.0) + (1 - edge) / len(tier)
    probs[0] = probs.get(0, 0.0) + edge
    ms = sorted(probs)
    return BetType(f"wheel:{difficulty}-{segments}", tuple(m - 1.0 for m in ms), tuple(probs[m] for m in ms))


# --------------------------------------------------------------------------- Plinko
# [V] each row is a fair left/right bit (top bit of a byte), so the hole is Binomial(rows, 1/2);
# payout tables are fixed per risk/rows (lightning mode is excluded: its board is re-drawn and
# its tables target a 4% edge per the verifier).
PLINKO = {
    "low": {8: [5.6, 2.1, 1.1, 1, 0.5, 1, 1.1, 2.1, 5.6],
            12: [10, 3, 1.6, 1.4, 1.1, 1, 0.5, 1, 1.1, 1.4, 1.6, 3, 10],
            16: [16, 9, 2, 1.4, 1.4, 1.2, 1.1, 1, 0.5, 1, 1.1, 1.2, 1.4, 1.4, 2, 9, 16]},
    "medium": {8: [13, 3, 1.3, 0.7, 0.4, 0.7, 1.3, 3, 13],
               12: [33, 11, 4, 2, 1.1, 0.6, 0.3, 0.6, 1.1, 2, 4, 11, 33],
               16: [110, 41, 10, 5, 3, 1.5, 1, 0.5, 0.3, 0.5, 1, 1.5, 3, 5, 10, 41, 110]},
    "high": {8: [29, 4, 1.5, 0.3, 0.2, 0.3, 1.5, 4, 29],
             10: [76, 10, 3, 0.9, 0.3, 0.2, 0.3, 0.9, 3, 10, 76],
             12: [170, 24, 8.1, 2, 0.7, 0.2, 0.2, 0.2, 0.7, 2, 8.1, 24, 170],
             13: [260, 37, 11, 4, 1, 0.2, 0.2, 0.2, 0.2, 1, 4, 11, 37, 260],
             16: [1000, 130, 26, 9, 4, 2, 0.2, 0.2, 0.2, 0.2, 0.2, 2, 4, 9, 26, 130, 1000]},
}


def plinko(risk: str, rows: int) -> BetType:
    table = PLINKO[risk][rows]
    probs: dict[float, float] = {}
    for k, m in enumerate(table):
        probs[m] = probs.get(m, 0.0) + comb(rows, k) / 2 ** rows
    ms = sorted(probs)
    return BetType(f"plinko:{risk}-{rows}", tuple(m - 1.0 for m in ms), tuple(probs[m] for m in ms))


# --------------------------------------------------------------------------- Towers
# [V] geometry per row (verifier, 2026-11-13): easy 4 tiles/1 trap, medium 3/1, hard 2/1,
# expert 3/2, crazy 4/3; 8 rows; each row independent.
# [3] the published multipliers equal (0.96/q)^level exactly (e.g. easy 1.28^n, crazy 3.84^n),
# i.e. a 4% edge applied per level, so cashing out after n levels returns 0.96^n.
TOWERS_SAFE = {"easy": 3 / 4, "medium": 2 / 3, "hard": 1 / 2, "expert": 1 / 3, "crazy": 1 / 4}


def towers(difficulty: str, levels: int) -> BetType:
    q = TOWERS_SAFE[difficulty]
    m = round((0.96 / q) ** levels, 2)            # the game shows and pays 2-decimal multipliers
    return two_outcome(f"towers:{difficulty}-L{levels}", m, q ** levels, "3",
                       "geometry verified; multiplier table third-party")


# --------------------------------------------------------------------------- Mines (unverified)
# [V] 25/36/49/64 tiles, 1..N-1 mines, a uniformly random layout. Roobet publishes no
# multiplier table; secondary sources say 96% or 97% RTP. Modelled as RTP * fair multiplier.
def mines(n_mines: int, picks: int, grid: int = 25, rtp: float = 0.96) -> BetType:
    p = comb(grid - n_mines, picks) / comb(grid, picks)
    m = np.floor(rtp / p * 100) / 100
    return two_outcome(f"mines:{n_mines}m-{picks}p-rtp{rtp:.2f}", m, p, "3", "multiplier table unverified")


# --------------------------------------------------------------------------- Coinflip
# [P] PvP/bot coinflip: the winner receives the pot minus a 4% fee -> 1.92x at 50%.
def coinflip() -> BetType:
    return two_outcome("coinflip", 1.92, 0.5, "H", "4% fee from Game Policy")


def summary_table() -> list[dict]:
    """RTP of each verified or modelled bet type that can matter for a 10x target."""
    rows = []
    for b in [dice(9.90), dice(49.50), limbo(10), limbo(2), slide(10), crash(10), crash(2),
              wheel("high", 10), wheel("medium", 10), wheel("low", 10),
              roulette("green"), roulette("bait"), roulette("red"), roulette("red", False),
              plinko("high", 16), plinko("high", 10), plinko("medium", 16), plinko("low", 16),
              towers("crazy", 1), towers("crazy", 2), towers("easy", 8),
              mines(1, 1), mines(24, 1), coinflip()]:
        win = sum(p for n, p in zip(b.net, b.prob) if n > 0)
        rows.append(dict(bet=b.name, rtp=b.rtp, edge=b.edge, p_win=win,
                         max_mult=max(b.net) + 1, verified=b.verified, note=b.note))
    return rows
