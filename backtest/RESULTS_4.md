# Round 4: hunting for "70% win rate at 1:3". Result: not found, and not close

**Bottom line:**
- **The pre-registered test:** about 17,000 new combinations, 6,145 of them at 1:3. Strategies from forums, Discord-style ICT/SMC models, papers and my own combinations. A machine-learning filter on 49,000 setups. All of it was tested on development data, then run once on a locked holdout.
- **The result:** nothing reached 70% at 1:3. Nothing came close.
- **Hindsight check:** even choosing the best of 4,265 settings directly on the holdout data, which is cheating on purpose to bound the possibility, the best true 3R-target-hit rate is **36.7%**.
- **Best real result:** NB3 V2 is still the best: **48% win rate, 11.6% full-target hits, +0.255R per trade** on the holdout.

## 1. What "70% at 1:3" requires

- **The price:** 70% wins at 1:3 means +1.8R per trade before costs, about 7 times NB3 V2's edge.
- **Random baseline:** in a market without an edge, the price reaches +3R before -1R **25%** of the time. Costs push that lower.
- **What it takes to get to 70%:** model the price as a random walk with drift μ and volatility σ. Then P(+3R before -1R) = (1 - e^θ) / (e^-3θ - e^θ), with θ = 2μR/σ².
  - It reaches 70% only at θ ≈ 1.2.
  - **In plain terms:** in the time random noise typically moves price by 1R, the trade's own drift would have to move it 0.6R in your favour, every time.
  - **For comparison:** the best documented intraday predictors explain about 1% of the next move's variance (Gao et al. 2018: out-of-sample R² 1.2%).
- **What forums and vendors report:** the claims are unverified or ill-defined.
  - Take Profit's 69.7% "Judas swing" figure is a vendor claim with an undefined "success".
  - An r/algotrading strategy with an 80% win rate broke when its data was shifted by 30 minutes.

## 2. The "win rate" trap

A **win** below means net R > 0. A trade closed at 15:55 slightly green counts as a win, so a wide stop inflates the win rate even though the full 3R is almost never reached.
- **Development:** the highest win rate at 1:3 was **66.7%** (SMH, NR7 day + 5-minute ORB, 0.5 ATR stop). **0%** of those trades hit 3R.
- **Holdout:** the same setting won 37.8% and lost -0.243R per trade.

The literal meaning of "70% at 1:3" is the **target-hit rate**, so both rates are always reported.

## 3. What was tested

| Family | Source of the idea | Best holdout finalist (1:3) |
|---|---|---|
| Candle Range Theory (first 30/60 min range sweep) | Discord/YouTube SMC ("CRT") | no finalist; 2 of 380 dev settings eligible, best +0.07R (t 0.8) |
| Prior-day high/low sweep, structural stop | ICT liquidity sweep | META: 38% win, 13% target, +0.075R (n=198) |
| Judas swing / Power of 3 (AMD) | ICT; [MQL5 gold test](https://www.mql5.com/en/blogs/post/778873), [FXNX on definitions](https://fxnx.com/en/blog/power-three-completion-rate-how-often-po3-plays-out), [vendor claim](https://takeprofitapp.com/en/learn/ict-judas-swing-explained) | AAPL: 19% win, -0.287R (n=213) |
| ICT 2022 model (sweep, displacement FVG, retrace) | ICT | no finalist; best dev +0.305R on n=70 (t 1.4) |
| NR7 / NR4 / inside day + ORB | Crabel | dev star NVDA 42.9% target hit; holdout **17.4%**, -0.315R |
| "Stocks in play" ORB, first-bar relative volume | Zarattini, Barbon & Aziz (2024) | SMH: 36% win, 17% target, +0.077R (n=53) |
| Turtle soup (failed 10/20-day breakout) | Connors & Raschke; [no reliable published win rate](https://therighttrader.com/learn/trading-strategies/turtle-soup) | no finalist; too rare per instrument, pooled -0.04R |
| Market Profile 80% rule | Dalton / forums | no finalist; best in hindsight: SPY 36.7% target hit |
| Holy Grail (daily trend + VWAP pullback) | Raschke ([rules](https://capital.com/en-gb/learn/trading-strategies/holy-grail-trading-strategy)) | SMH/META: about breakeven or negative |
| Last-half-hour momentum | Gao, Han, Li & Zhou (2018); [cross-country replication](https://nottingham-repository.worktribe.com/OutputFile/5273196), [QuantConnect](https://www.quantconnect.com/learning/articles/investment-strategy-library/intraday-etf-momentum) | TSLA: 54% win, 0.3% target, +0.029R |
| Gap-and-go with relative volume | day-trading forums | no finalist; pooled -0.04R |
| Opening drive | Steidlmayer / forums | TSLA: 41% win, 10% target, +0.127R (n=69) |
| NB3 V2 + one confluence filter (13 filters) | own combinations | TSLA + NR7 filter: 56% win, 8% target, +0.30R, **n=36 only** |
| SMT divergence, 13 pairs | ICT | pooled: 48.6% win, 1.7% target, -0.009R |
| Meta-labeling model (gradient-boosted trees, 23 features) | López de Prado | top 10%: 22% target, -0.136R |

[FXStreet's column](https://www.fxstreet.com/education/the-biggest-lie-in-trading-202304231813) on 70%-win-rate claims sums up the forum evidence well.

## 4. Results

**Development** (2023-03 .. 2024-12, `results_round4/dev_selection.md`):
- **Grid size:** 6,145 rows at 1:3, 578 of them eligible.
- **Highest win rates:** 66.7% (SMH NR7 ORB, 0.5 ATR stop, 0% target hit) and 61.6% (TSLA NR4 30-min ORB).
- **Highest 3R target-hit rate:** 42.9% (NVDA NR7 + 5-minute ORB, 0.1 ATR stop, n=70).

**Holdout** (2025-01 .. 2026-03, run once, `results_round4/holdout_finalists.md`):
- **Finalists:** 27 new finalists plus the NB3 V2 reference.
  - **Positive:** 9 of the 27 new finalists had a positive average R.
  - **Negative:** 18 had a zero or negative average R.
- **Best new finalist:** TSLA NB3 + NR7, +0.30R, but n=36, with a 95% interval on the win rate of 40-70%. The 2026 part was -0.2R.
- **Ones that collapsed:**
  - NVDA NR7 ORB: target hit 42.9% → 17.4%;
  - SMH NR7 ORB: win 66.7% → 37.8%;
  - QQQ NR4 ORB: +0.363R → -0.093R.
- **NB3 V2 reference:** 48.1% win, 11.6% target hit, **+0.255R**, profit factor 1.55. It is still the best.

**Meta-labeling** (`results_round4/meta_*.json`):

| | Development (out-of-fold) | Holdout |
|---|---|---|
| AUC | 0.690 | 0.692 |
| All setups: target hit / avg R | 11.8% / -0.130R | 12.5% / -0.083R |
| Top 10% by model: target hit / avg R | 20.8% / -0.163R | 22.2% / -0.136R |
| Top 3% by model: target hit / avg R | 21.2% / -0.138R | 14.8% / -0.461R |

The model's skill is real and stable, since the AUC held on the holdout. But it mostly learned that a tight stop reaches its target more often, and costs make those trades lose. It does not find profitable trades.

**Hindsight diagnostic** (`results_round4/hindsight.txt`, NOT used for selection). The whole grid was run on the holdout (4,265 settings with n >= 40):
- **No setting reached 70%**, by either measure:
  - highest win rate 66%: SPY NB3 + NR7, 0.5 ATR stop, n=50, 0% target hits;
  - highest target-hit rate 36.7%: SPY 80% rule, 0.1 ATR stop, n=90.
- **Development rankings partly carry over:**
  - **Average R:** the top 10% by development average R (+0.158R) earned +0.045R on the holdout, against -0.066R for all settings.
  - **Win and target-hit rates:** their rank correlation is high (0.82 and 0.93), but that is mostly the stop size talking, not an edge.

## 5. What this means

- **The goal itself:** no tested strategy, and no verifiable public one, delivers 70% at 1:3. Treat any course, Discord group or indicator that claims it as unproven until it shows a pre-registered, out-of-sample, cost-inclusive record.
- **Raising the win rate isn't the lever:** a higher win rate at the same 1:3 needs a far stronger edge, not a better filter. Filters that raised the in-sample win rate here gave it back on the holdout.
- **What's actually available:**
  - **NB3 V2:** about 45-48% win rate at 1:3, about 11% full-target hits, and +0.2 to +0.25R per trade. It held for two years out of sample, plus the Yahoo Sep–Nov 2026 check.
  - **What would improve results:** adding uncorrelated small edges (more trades per day), and controlling risk. Chasing a higher win rate would not.

## 6. Reproduce

```
CACHE=<inst cache>
python3 backtest/run_grid4.py --cache $CACHE --period dev --out backtest/grid4_dev.csv
python3 backtest/select4.py pick --dev backtest/grid4_dev.csv --out backtest/finalists_round4.json
python3 backtest/run_grid4.py --cache $CACHE --period holdout --only backtest/finalists_round4.json --out backtest/grid4_holdout_finalists.csv
python3 backtest/select4.py table --csv backtest/grid4_holdout_finalists.csv --keys backtest/finalists_round4.json
python3 backtest/meta4.py --cache $CACHE --stage dev        # then --stage holdout (once)
python3 -m unittest tests.test_lab4
```
