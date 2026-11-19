# Roobet $10 → $100 study

Exact mathematics and Monte Carlo for the question "what gives the highest chance of turning
$10 into $100 on Roobet?". Game rules come from the verifier code Roobet links from
https://roobet.com/fair (fetched 2026-11-19); see `games.SOURCES`.

| File | What it does |
| --- | --- |
| `games.py` | Payout models per game, each tagged with its source (verifier / help centre / inferred / third party) |
| `engine.py` | Two-outcome game quotes (Dice, Limbo, Crash, menus), betting systems, vectorised Monte Carlo, exact Markov-chain solver |
| `multi.py` | Multi-outcome bets (Plinko, Roulette, Towers, Blackjack): simulation, exact evaluation, grid dynamic programming |
| `exact.py` | Closed forms (ceiling, single bet, k stages, continuous optimum, gambler's ruin) and cent-exact DP |
| `blackjack.py` | Infinite-deck basic strategy with full outcome distributions (S17, 3:2, peek / no-peek) |
| `hilo.py` | HiLo: best plan with unlimited skips and a finite-skip DP on a log-multiplier grid |
| `run_roobet.py` | Runs everything (147 jobs, 100,000 challenges each) → `results/roobet_results.json` |
| `autobet.py` | Phase 3: Roobet Auto Bet (on win/on loss reset or % increase, stop on profit/loss, halting when the next bet does not fit; optional manual finish) and the "every win lands on $100" geometric family |
| `tabular.py` | Phase 3: any bankroll-only policy as a transition table (multi-game, multi-outcome, mixtures): exact solve and 1M-challenge simulation |
| `baccarat.py` | Phase 3: exact 8-deck Punto Banco probabilities (third-party live tables; payouts assumed standard) |
| `fairsim.py` | Phase 3 validation: challenges played with dice rolls derived exactly as Roobet's Dice verifier does (HMAC-SHA512), independent of the engine |
| `run_phase3.py` | Phase 3 ($20 → $100): DP optima, game-switching union DP and optimality checks, Auto Bet search, 46 strategies × 1,000,000 challenges, provably-fair validation → `results/phase3_results.json` |

```bash
cd roobet && python3 run_roobet.py            # $10 study, ~2.5 min on 4 cores
cd roobet && python3 run_phase3.py            # $20 study, 1M challenges per strategy, ~15 min on 4 cores
python3 -m unittest tests.test_roobet tests.test_roobet_phase3 -v      # from the repo root
```

Seeds: strategy job *i* uses seed 1000+*i* (sample A); optimisation candidates use 1777+*i*
(sample A) and 5777+*i* (sample B). Every deterministic strategy is also solved exactly.

Key identity: for any strategy, E[final] = 10 − edge × E[total wagered], hence
P($100) ≤ (10 − 9.99·e)/(100 − 9.99·e). Best found: one all-in Dice bet at 10× (9.900%;
99% RTP inferred), HiLo plan (9.894%; 1% edge verified), Limbo 10× (9.800%; verified).
