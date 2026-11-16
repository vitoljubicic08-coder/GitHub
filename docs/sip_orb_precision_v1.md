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
