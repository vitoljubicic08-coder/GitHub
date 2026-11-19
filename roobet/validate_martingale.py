"""Follow-up check of the Martingale Auto Bet validation ($0.10 at 2x, +100% on loss, $20 -> $100).

    python3 validate_martingale.py 250000 py 11      # plain Python RNG, same logic as fairsim
    python3 validate_martingale.py 40000 hmac 77     # dice rolls from Roobet's HMAC-SHA512 derivation

Prints the success rate and its z-score against the exact value 7.47616%.
"""
import random, sys
sys.path.insert(0, ".")
import fairsim as F
import numpy as np

def run(n, seed, use_hmac):
    rng = random.Random(seed)
    won = 0
    for _ in range(n):
        pl = F.Player(rng) if use_hmac else None
        B, j = 2000, 0
        while 0 < B < 10000:
            s = int(10 * 2 ** j + 0.5 + 1e-9)
            if s > B:
                break
            w = pl.dice(4950) if use_hmac else (rng.random() < 0.495)
            if w:
                B = B - s + 2 * s; j = 0
            else:
                B -= s; j += 1
        won += B >= 10000
    return won / n

n = int(sys.argv[1]); mode = sys.argv[2]
p = run(n, int(sys.argv[3]), mode == "hmac")
se = np.sqrt(0.0747616 * (1 - 0.0747616) / n)
print(mode, n, p, "z", (p - 0.0747616) / se)
