# SIP-ORB Precision V1

A volume-filtered 5-minute Opening Range Breakout for individual US-listed stocks. It is inspired by the
"Stocks in Play" research of Zarattini, Barbon & Aziz (SFI Research Paper N. 24-98). It changes their
method and does not reproduce their published backtest. No profitability or win rate is claimed, and no
backtest result is reported here.

| File | Purpose |
|---|---|
| `sip_orb_precision_v1_indicator.pine` | Production indicator (`indicator()`, overlay): two arrows and two alert conditions |
| `sip_orb_precision_v1_strategy.pine` | Backtesting strategy (`strategy()`) with the same signal engine |
| `tests/sip_orb_reference_engine.py` | Offline Python mirror of the Pine engine and the position-sizing rule |
| `tests/test_sip_orb_precision_v1.py` | Validation tests A–I, boundary tests, and static checks on both `.pine` files |

Both scripts are written in Pine Script **v6**, as the specification requires.

## Rules, in brief

* **Opening range:** the 09:30–09:35 ET candle (its high, low, open, close and volume), captured when the candle closes.
* **Direction:** if the opening candle is bullish, only BUY signals are allowed that day. If it is bearish, only SELL. If it is a doji, no signals.
* **Eligibility (frozen at 09:35):** all of these must hold:
  * openingOpen > $5.00
  * the mean daily volume of the previous 14 sessions is at least 1,000,000
  * the previous day's ATR(14) is above $0.50
  * the opening RVOL is at least 2.0, measured against the opening-candle volumes of the 14 previous sessions
* **Signal:** the first confirmed close beyond the opening high (BUY) or low (SELL), on a bar that opens between 09:35 and 10:55 ET. One signal per session.
* **Backtest:**
  * Risk is 0.25% of equity, and notional is capped at 100% of equity.
  * The stop is 10% of the previous day's ATR(14), measured from the actual fill price.
  * There is no profit target.
  * The end-of-day close is submitted on the 15:50 bar and fills at the 15:55 open.
  * Costs are $0.005 per share per side plus 2 ticks of slippage.

## How the two scripts stay identical

The block between `// ==== BEGIN SIP-ORB SIGNAL ENGINE` and `// ==== END SIP-ORB SIGNAL ENGINE ====` is
byte-identical in both files. `test_signal_engine_is_byte_identical` enforces this. When you edit the
engine, edit the indicator and copy the whole block into the strategy.

## Running the offline validation

```bash
python3 -m unittest discover -s tests -v
```

The Python model checks the **algorithm**: session reset, update order of the rolling array, thresholds,
signal window, one-signal lock, DST handling and confirmed-bar gating. It cannot compile Pine or simulate
TradingView's data feed. The static tests check the Pine sources for these things:

* forbidden visuals, offsets and inputs
* the `[1]` + `lookahead_on` daily request
* the alert titles and messages
* the strategy properties
* the absence of take-profit and trailing parameters
* indentation and bracket balance

| Spec test | Automated test(s) |
|---|---|
| A Valid BUY | `test_A_valid_buy` |
| B Wick only | `test_B_wick_without_close_is_rejected` |
| C Valid SELL | `test_C_valid_sell` |
| D RVOL 1.99 | `test_D_rvol_below_threshold_is_rejected`, `test_D_rvol_exactly_two_is_accepted` |
| E Doji | `test_E_opening_doji_blocks_the_day` |
| F Duplicates | `test_F_one_signal_per_session_then_reset` |
| G Repainting | `test_G_realtime_replay_matches_history` (model level; also check in TradingView, below) |
| H Timezone | `test_H_window_tracks_new_york_time_across_dst`, `test_H_window_end_is_exclusive_at_11_00_local` |
| I History | `test_I_insufficient_opening_volume_history`, `test_I_invalid_history_observation_is_not_counted` |

## Checks to run in TradingView

1. **Compile:** paste each file into the Pine Editor and click *Add to chart*. These scripts were not
   compiled in TradingView during development.
2. **Rejection:** open a 15-minute chart, an ETF such as `AMEX:SPY`, or a Heikin Ashi chart. The script
   should stop with a "SIP-ORB V1 rejected" runtime error.
3. **Parity:** put both scripts on the same 5-minute stock chart.
   * The arrows must sit on the same candles.
   * In the Data Window, `Diag: signal` must match on every bar.
   * In the Strategy Tester's *List of Trades*, each entry must be at the open of the bar after an arrow.
4. **Test G (repainting):** use Bar Replay on a day that has a signal. Step forward one bar at a time.
   * The arrow must appear only when its candle closes, never while it is forming.
   * Leave replay or reload the chart. The arrow must still be on the same candle.
   * Live check: note the bar time in an alert, then reload the chart the next day.
5. **Test H (timezone):** look at signal days in January (EST) and July (EDT).
   * Every arrow must be on a bar whose New York open time is between 09:35 and 10:55.
   * Switch the chart's display timezone, for example to UTC. The arrows must stay on the same candles.
6. **Test I:** in the first 14 sessions loaded on the chart, `Diag: opening-volume observations` is below
   14 and no arrows appear.
7. **Alerts:** create alerts on "SIP-ORB BUY" and "SIP-ORB SELL" with frequency **Once Per Bar Close**.

## Quality checklist (specification §14)

1. **Syntax and functions.** The scripts use only documented v6 built-ins:
   * `request.security`, `ticker.modify`, `ta.atr`, `math.sum`
   * the `session.*`, `timeframe.*`, `chart.is_standard` and `syminfo.*` variables
   * array methods, `runtime.error`
   * `strategy.entry` / `exit` / `close_all(immediately)` / `cancel_all`

   Two v6 rules are handled explicitly. Booleans cannot be `na`, so they are initialised to `false`. Logic
   is short-circuited, which makes `na(sessDateKey) or ...` safe. The scripts were not compiled here; see
   "Checks to run in TradingView" above.
2. **Daily leakage.** The only higher-timeframe call is `request.security(..., "D", [ta.atr(14)[1],
   math.sum(volume, 14)[1]], lookahead = barmerge.lookahead_on)`. This is TradingView's documented
   non-repainting pattern: on every intraday bar of day T it returns day T-1's completed values. The
   values are sampled once, on the 09:30 bar, and then frozen.
3. **Rolling array.** The array is declared with `var` and starts empty. On each 09:30 bar the steps run in
   this order:
   * check that the array holds exactly 14 values
   * compute the ratio and run the threshold test
   * push today's volume if it is greater than 0
   * shift the oldest value out if there are more than 14

   Days with zero, `na` or missing opening volume are never stored.
4. **Session reset and first bar.** State resets on the first *confirmed regular-session* bar of each new
   New York date (`yyyymmdd`). The opening range is captured only if that bar opens at exactly 09:30 ET.
   Premarket and after-hours bars fail `inRegular` (`session.ismarket` plus the 09:30–16:00 ET clock) and
   are never processed.
5. **Holidays and missing data.** Holidays produce no bars, so they create no session. If a day has no
   09:30 candle, or that candle's data is invalid, the whole session is blocked. Missing or zero daily
   ATR or volume fails its filter, because comparisons with `na` are false.
6. **Same engine.** The engine block is byte-identical and enforced by a test. The strategy only reads
   `buySignal`, `sellSignal`, `sessPrevAtr`, `sessDateKey`, `sessionStarted`, `inRegular` and `nyMod`.
7. **No duplicates or repainting.**
   * `sessSignalLocked` blocks a second signal in the same session.
   * All state changes happen under `barstate.isconfirmed`.
   * There are no offsets, pivots, `security_lower_tf` calls or future references.
8. **Remaining limitations:** see below.

## Offline backtest (Python replication, Yahoo Finance data)

This is **not** a TradingView Strategy Tester run. `backtest/sip_orb_backtest.py` replays Yahoo Finance
5-minute bars through the reference engine. It also runs a broker emulator that applies the strategy's
rules: next-bar-open fills, 2 ticks of slippage per fill, a stop at 10% of ATR measured from the fill,
$0.005 per share per side, and the end-of-day exit at 15:55. Each symbol is its own $10,000 account,
as in TradingView.

* **Data:** 2,961 US common stocks from the NASDAQ Trader listings, loosely pre-filtered on price and
  volume. 5-minute bars cover 2026-08-21 to 2026-11-13, which is Yahoo's 60-day limit. The first 14
  sessions only build the opening-volume history, so trades run from 2026-09-11.
* **Result:** 3,419 trades on 1,299 symbols.
  * Win rate 13.3%, average **−0.26R** (median −1.14R), profit factor **0.76**.
  * Bootstrap 95% CI of the mean: **[−0.36R, −0.16R]**.
  * The first 1,000 trades in time order: average −0.35R, profit factor 0.68.
* **Where the losses come from:** frictionless R (slippage and commission removed) averages
  **+0.09R**.
  * The median stop distance is $0.17, so the specified friction (4¢ slippage plus 1¢ commission per
    share per round trip) costs about 0.29R per trade.
  * The damage is worst on $5–20 stocks: average −0.52R, profit factor 0.58.
* **Fat tails:** 470 trades reached the end-of-day exit and averaged +5.7R. The best 5% of trades
  produced +1,816R, and without them the average is −0.83R.
* **Caveats:**
  * 60 days is one short market regime.
  * The listing only includes stocks that exist today, so delisted names are missing (survivorship
    bias).
  * Yahoo bars and volumes can differ from TradingView's feed.
  * The results add up independent accounts. They are not one portfolio.

Files: `backtest/results/summary.json`, `backtest/results/trades.csv`, `backtest/results/breakdown.txt`.
To reproduce:

```bash
pip install yfinance pandas
python3 backtest/fetch_yahoo_data.py --out data
python3 backtest/sip_orb_backtest.py --data data --out backtest/results --min-trades 1000
python3 backtest/analyze_trades.py backtest/results/trades.csv
```

## Multi-year backtest (3 years, public 1-minute data)

`backtest/run_hf_backtest.py` replays the public Hugging Face dataset `Rrishab/OHLCV-1m` for
2023-03 to 2026-03. That dataset holds 1-minute bars sourced by its author from Finnhub; its license
was not verified.

* **Data preparation:**
  * The 1-minute bars are combined into regular-session 5-minute bars.
  * Daily volume is the full-day sum, which matches Yahoo's official daily volume to within about 3%.
  * The dataset is not split-adjusted, so prices and volumes are adjusted with Yahoo's split
    history, the way TradingView adjusts its charts.
* **Universe:** every current US common stock, 4,973 of which have data. Delisted stocks are
  missing (survivorship bias).
* **Result:** 36,450 trades on 1,870 stocks.
  * Win rate 12.3%, average **−0.28R**, profit factor **0.75**.
  * Bootstrap 95% CI of the mean: [−0.31R, −0.25R].
  * Every year, and both longs and shorts, lost money.
  * Before commission the average is −0.20R.
* **Choosing stocks:** ranking stocks on 2023-03 → 2025-03 (at least 10 trades) gives VKTX, CDNS,
  NVAX, MSTR and AKAM. In 2025-04 → 2026-03 these five lost: 65 trades, −0.33R average, profit
  factor 0.67, which is worse than all stocks combined (−0.17R).
  * Ranking all 765 stocks into quintiles on the first two years, even the best fifth averaged
    −0.01R in the final year.
* **Hindsight top 5 (VKTX, TTWO, THC, BWA, CDNS):** luck alone would produce a top 5 this good about
  2.8% of the time, and each of these stocks had losing or flat years.

Files: `backtest/results_3y/` (`summary.json`, `trades.csv.gz`, `top5.txt`, `breakdown.txt`).
To reproduce:

```bash
pip install yfinance pandas pyarrow
python3 backtest/run_hf_backtest.py --start 2023-03 --end 2026-03 --cache /tmp/hf --out results_hf
python3 backtest/select_top_stocks.py results_hf/trades.csv --split 2025-04-01 --min-trades 10
```

## Strategy research: fixing ORB and alternatives

**Goal:** a strategy that is consistent across years with a high win rate. **Method:**
* Develop only on 2023-03 → 2024-12.
* Commit the finalists before looking at the locked holdout (2025-01 → 2026-03), see
  `backtest/SHORTLIST.md`.
* Then run one independent check on Yahoo data, Sep–Nov 2026.
* Every variant is logged in `backtest/research_log.csv`: 63 runs on development data, plus the
  holdout and Yahoo checks.

Tools:
* `build_candidate_cache.py`: one pass that stores the 1-minute path of every candidate stock-day.
* `variant_lab.py`: a vectorised simulator. Replaying V1 at 5-minute resolution, it reproduced all
  4,414 event-driven trades.
* `index_momentum.py`: the SPY/QQQ momentum simulator.

**Stock ORB fixes (all after V1 costs):**
* **The paper's own setup is worst under V1 costs** (top-20 RVOL, stop-order entry, 10%-ATR stop):
  −0.61R.
* **Wider stops cut the cost drag most.** Stopping at the other side of the opening range gives
  −0.02R and a 43% win rate.
* **Filters did not help.**
  * Gap direction, SPY direction, side, RVOL tiers and premarket volume made no difference.
  * The premarket-volume filter peaked at a single threshold, a sign of noise.
  * Price ≥ $50–100 and a minimum $ stop help only by cutting costs.
* **Before costs** the edge is about +0.03–0.05R per trade. That is too small to survive 2 ticks of
  slippage per fill.
* **Finalist E04** (top-20 RVOL, stop entry, range stop, stop ≥ $2): +0.015R on development data,
  **+0.001R on the holdout**, so no edge.
* **Profit targets raise the win rate but not profits.** A 0.5R target gives a 61% win rate and
  −0.025R.

**SPY/QQQ intraday "noise-area" momentum** (Zarattini, Aziz & Barbon 2024, published defaults,
untuned):

| QQQ, unlevered, after costs | Result |
|---|---|
| 2023 (development) | +11.7% |
| 2024 (development) | +7.4% |
| 2025 (holdout) | +10.6% |
| 2026 Q1 (holdout) | +1.9% |
| Sep–Nov 2026 (Yahoo, independent) | +4.0% |

* Sharpe: 1.77 on development, 0.96 on the holdout, 2.38 on the Yahoo check.
* Positive months: 26 of 40.
* Maximum drawdown: −6.8%.
* Per-trade win rate: 38–42%.
* SPY holdout: Sharpe 0.28, weak.
* Exits use the "no churn" rule: hold instead of exit-and-rebuy at the same check. This only
  removes fees; the positions are unchanged.

**The win-rate trade-off, measured on QQQ development data:**

| Target | Win rate | 2-year return |
|---|---|---|
| None | 42% | +18.5% |
| 0.30% | 54% | +10.8% |
| 0.15% | 67% | +3.3% |

A tight target lifts the win rate but destroys most of the profit, so the final version has no
target.

**Pine scripts:** `nam_momentum_v1_indicator.pine` and `nam_momentum_v1_strategy.pine`. They are
Pine v6 on 5-minute QQQ (or SPY) charts and share a byte-identical engine block.
`tests/nam_reference_engine.py` mirrors that engine bar by bar. It reproduces the research simulator
trade for trade, except on the few days around outages in the dataset: 2023-03-13/14 and
2024-11-13/15, when QQQ was missing 54–76 of 78 bars. Results on 5-minute bars match the 1-minute
results.

## Round 2: arrow strategies with a fixed 1:3 (or other) reward:risk

**Request:** an indicator with green and red arrows that is right 70% of the time at about 1:3.

**The arithmetic:** at 1:3 the break-even win rate is 25%, and random entries hit +3R before -1R
about 25% of the time. A 70% win rate at 1:3 would earn +1.8R per trade. The best strategies found
here earn about 0.1-0.3R.

**What was tested:** pre-registered in `backtest/SHORTLIST_2.md`, with every result in
`backtest/grid_dev.csv`.
* 18 instruments: SPY, QQQ, IWM, DIA, GLD, SLV, TLT, USO, XLE, XLF, SMH, AAPL, NVDA, TSLA, AMZN,
  MSFT, META, AMD.
* 24 signal settings: VWAP standard-deviation fade/break, noise-band fade/break, ORB, failed ORB,
  RSI extremes, gap fade, VWAP pullback.
* 3 stop sizes, 1-2 trades per day, and 5 reward:risk levels.
* 12,960 combinations in total, with V1 costs.

The engine (`backtest/intraday_lab.py`) was calibrated against random arrows, which match the
theoretical 1/(1+RR).

| Reward:risk | Random win rate | Best found (dev) | Median (dev) |
|---|---|---|---|
| 1:0.33 | 75% | 79% | 69% |
| 1:0.5 | 67% | 71% | 62% |
| 1:1 | 50% | 55% | 47% |
| 1:2 | 33% | 50% | 35% |
| 1:3 | 25% | 48% | 32% |

* **No combination reached 70% at 1:3,** and none reached 50% at 1:3.
* Of the 12 pre-registered finalists, only the **QQQ noise-band breakout at 1:3** held up on the locked
  holdout and the independent Yahoo check.

**NB3 Breakout V1:** QQQ, 1.5x noise band, stop 0.2 x ATR, 1:3, one trade per day.

| Period | Win rate | Avg per trade |
|---|---|---|
| Development 2023-24 | 36.1% | +0.174R |
| Holdout 2025-26 Q1 | 37.4% | +0.132R |
| Yahoo Sep-Nov 2026 | 33.3% | +0.288R |

With the strategy's sizing (risk 0.25% per trade, no leverage), $100 became $121.74 over
2023-03 .. 2026-03:

| Year | Return |
|---|---|
| 2023 | +4.0% |
| 2024 | +10.1% |
| 2025 | +3.8% |
| 2026 Q1 | +2.4% |

* The worst dip was -5.2%.
* On the Yahoo check, $100 became $102.78.
* Pine files: `nb3_breakout_v1_indicator.pine` and `nb3_breakout_v1_strategy.pine`.
* `tests/nb3_reference_engine.py` reproduces the grid engine's entries exactly, except on 6 days just
  after outages in the dataset.

## Round 3: optimising for prop-firm evaluations (one-month pass probability)

**Objective:** the chance of passing a $50K evaluation (+$3,000 before a $2,000 trailing drawdown)
within one month, at up to 2 trades per day. The rule was pre-registered in
`backtest/SHORTLIST_3.md`, and all results are in `backtest/grid3_dev.csv` and
`backtest/grid3_holdout_finalists.csv`.

**What 70% requires:** about +0.35-0.40R per trade at ~40 trades per month. For example, 65% winners
at 1:1, 45% at 1:2, or 35% at 1:3, with full-size wins and losses.

**New concepts tested:** ICT liquidity sweeps of the prior-day high/low, prior-day breaks, fair value
gap retests (all day and the 10-11 "silver bullet" window), a cumulative-delta divergence order-flow
proxy, and initial-balance break/failure. They were added to the 24 earlier settings across 18
instruments, giving 18,270 combinations.
* None of the new concepts beat the existing momentum signals.
* The best one-month pass probability on development data was 45%.

**Holdout:** QQQ noise_break, band 1.0, stop 0.3 ATR, 1:3, one trade per day.

| Period | One-month pass probability |
|---|---|
| Development | 44% |
| Holdout | 52% |
| Yahoo Sep-Nov 2026 | 52% |
| Holdout days with the edge removed | 31% |

* Holdout trades: 48% winners, +0.255R, profit factor 1.55.
* Two-instrument versions reached 52-55% on the holdout (QQQ + SPY is futures-tradable).
* Implemented as `nb3_breakout_v2_indicator.pine` / `_strategy.pine`. The engine block is identical to
  V1's apart from the settings and allowed symbols.
* The bar-by-bar mirror selects the same entries as the grid engine, apart from a few days affected by
  dataset outages and one half-day session (Nov 29, 2024) that TradingView would show without
  afternoon bars.

## Known limitations

* **Not compiled here.** The scripts were reviewed against the v6 reference but not compiled in
  TradingView. Run the compile check above first.
* **Data feed.** Intraday and daily volume depend on your TradingView data subscription.
  * A free plan's real-time Cboe BZX feed shows much less volume than the consolidated tape.
  * Whether the 09:30 candle includes the opening-auction cross depends on the vendor.
  * Daily-bar volume may not equal the sum of the intraday bars.
  * RVOL uses the same feed for both numerator and denominator. The absolute 1,000,000-share daily
    filter does not, so it is the most feed-sensitive input.
* **Data revisions.** If the vendor corrects historical OHLCV, the historical calculations and signals
  are recomputed from the corrected data.
* **Chart history depth.** The opening-volume history needs 14 sessions loaded on the chart. The first
  14 loaded sessions can never signal. When the loaded window moves forward, signals near the left
  edge of the chart can disappear. Signals that are already well inside the window do not change.
* **Instrument classification.** The script trusts TradingView's metadata:
  * `syminfo.type == "stock"`
  * prefix `NYSE`, `NASDAQ` or `AMEX`
  * currency `USD`

  ADRs (`"dr"`) and anything TradingView labels `"fund"` are rejected. The script cannot confirm
  common-share status beyond this metadata.
* **Early-close sessions.** On early-close days, the strategy relies on `session.islastbar_regular` to
  flatten at the close of the last regular bar. If TradingView does not flag that bar on a
  regular-hours-only chart, the failsafe closes the position at the close of the next session's first
  bar.
* **Fills.**
  * Entries fill at the next bar's open, not at the signal close.
  * Gaps and slippage change the realised risk away from the planned 0.25%.
  * A stop that is not on a tick boundary may be rounded to the tick size.
  * A gap at entry can push notional above 100%, which can trigger TradingView's margin model.
  * Bar Magnifier only works on plans that include it.
* **Price adjustment.** Dividend-adjustment settings change historical price levels and the daily ATR.
* **Alert frequency** is set in the alert dialog and cannot be enforced by `alertcondition()`. The
  conditions are only true at bar close, so with "Once Per Bar Close" each alert fires exactly once.
* **Diagnostics** use `display.data_window`. They are not drawn on the chart and do not show in the
  status line.

### Additional limitations (research round 2 and NAM V1)

* The Pine scripts (V1 and NAM V1) were not compiled in TradingView. Compile them in the Pine Editor
  before using them.
* **End-of-day edge case:** both strategies send the end-of-day close on the 15:50 bar for a fill
  at the 15:55 open. If a stock has no 15:55 bar, the order fills at the next bar, possibly the
  next morning. This happened in 2 of 4,414 V1 trades. It is practically impossible for QQQ/SPY.
* **NAM V1 has no intraday stop order.** Losses between half-hour checks are not capped.
* **The holdout was used once per finalist.** The no-churn change came afterwards, but it only
  removes duplicate fees.
* The 1-minute dataset has outages, and its universe has survivorship bias (current listings only).
