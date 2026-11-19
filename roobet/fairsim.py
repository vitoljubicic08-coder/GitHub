"""Independent validation: challenges played with dice rolls derived exactly as Roobet's Dice
verifier derives them (https://codesandbox.io/p/sandbox/6wmyl3, updated 2026-09-21).

    finalHash   = HMAC-SHA512(key = serverSeed, message = "clientSeed - nonce")
    entropyHash = HMAC-SHA512(key = finalHash, message = "0")
    U    = first 16 hex chars / 2^64, at 20 significant digits, half-up
    roll = 100 * U truncated to 4 decimals            (0.00 .. 99.99)

A bet "roll under c" wins when roll < c. Each challenge uses a fresh random server seed
(as after a seed rotation) and nonces 0, 1, 2, ... This shares no code with engine.py:
the randomness is SHA-512, the bookkeeping is plain Python, and Auto Bet is re-implemented
from the help-centre description.
"""
from __future__ import annotations

import hashlib
import hmac
import random
from decimal import ROUND_DOWN, ROUND_HALF_UP, Context, Decimal

_CTX = Context(prec=20, rounding=ROUND_HALF_UP)
_TWO64 = Decimal(2) ** 64
_Q4 = Decimal("0.0001")
TARGET = 10_000


def roll_hundredths(server_seed: str, client_seed: str, nonce: int) -> int:
    """The Dice roll in hundredths (0..9999), exactly as the verifier computes it."""
    final = hmac.new(server_seed.encode(), f"{client_seed} - {nonce}".encode(), hashlib.sha512).hexdigest()
    ent = hmac.new(final.encode(), b"0", hashlib.sha512).hexdigest()
    u = _CTX.divide(Decimal(int(ent[:16], 16)), _TWO64).quantize(_Q4, rounding=ROUND_DOWN)
    return int(u * 10000)


class Player:
    """One challenge's seed pair and nonce counter."""

    def __init__(self, rng: random.Random):
        self.server = "%064x" % rng.getrandbits(256)
        self.client = "%016x" % rng.getrandbits(64)
        self.nonce = 0

    def dice(self, chance_hundredths: int) -> bool:
        r = roll_hundredths(self.server, self.client, self.nonce)
        self.nonce += 1
        return r < chance_hundredths


def dice_chance(m_req: float, rtp: float = 0.99) -> int:
    """Win chance in hundredths of a percent for the cheapest multiplier >= m_req."""
    c = int(100.0 * rtp / m_req * 100 + 1e-9)
    return max(1, min(c, 9800))


def payout(stake: int, chance_h: int, rtp: float = 0.99) -> int:
    return int(stake * (100.0 * rtp / (chance_h / 100)) + 1e-9)


def play_policy(policy, n, seed, start=2000):
    """A target-hitting stake table (cents -> stake): every bet aims at $100."""
    rng = random.Random(seed)
    won = bets = 0
    wagered = 0
    for _ in range(n):
        pl = Player(rng)
        B = start
        while 0 < B < TARGET:
            s = max(1, min(int(policy[B]), B))
            c = dice_chance((TARGET - B + s) / s)
            bets += 1
            wagered += s
            B = B - s + payout(s, c) if pl.dice(c) else B - s
        won += B >= TARGET
    return dict(n=n, p_target=won / n, mean_bets=bets / n, mean_wagered=wagered / n / 100)


def play_autobet(base, chance_h, loss_pct, n, seed, start=2000, stop_profit=8000, finish=None):
    """Auto Bet: on win reset, on loss raise by loss_pct of the current bet (rounded half up
    to the cent), stop on profit; halts when the next bet exceeds the balance, unless a
    finishing policy table is given (then the rest is played by hand with that policy)."""
    rng = random.Random(seed)
    won = bets = 0
    final_sum = 0
    for _ in range(n):
        pl = Player(rng)
        B, j = start, 0
        while 0 < B < TARGET and B < start + stop_profit:
            s = int(base * (1 + loss_pct) ** j + 0.5 + 1e-9)
            if s > B:
                if finish is None:
                    break
                s = max(1, min(int(finish[B]), B))
                c = dice_chance((TARGET - B + s) / s)
                bets += 1
                B = B - s + payout(s, c) if pl.dice(c) else B - s
                continue
            bets += 1
            if pl.dice(chance_h):
                B = B - s + payout(s, chance_h)
                j = 0
            else:
                B -= s
                j += 1
        won += B >= TARGET
        final_sum += B
    return dict(n=n, p_target=won / n, mean_bets=bets / n, mean_final=final_sum / n / 100)


def roll_frequencies(n, seed):
    """Histogram of n rolls in 100 buckets of 1.00 (uniformity check of the derivation)."""
    rng = random.Random(seed)
    pl = Player(rng)
    h = [0] * 100
    for _ in range(n):
        h[roll_hundredths(pl.server, pl.client, pl.nonce) // 100] += 1
        pl.nonce += 1
    return h
