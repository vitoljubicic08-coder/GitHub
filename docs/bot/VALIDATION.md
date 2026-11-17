# NB3 V2 bot — validation record

## 1. Which implementation is "the" NB3 V2

The verified results (675 trades, 2023-03 to 2026-03, +0.195R per trade) were produced by:

- `backtest/intraday_lab.py`: the `noise_break` family with band 1.0, plus the noise band, ATR and 5-minute features;
- `backtest/nb3_trades.py`: `extract(d)`, which applies stop 0.30 × ATR, 1:3, the first signal per day, the next-bar-open entry and the 15:55 exit;
- default costs of 2 ticks of $0.01 slippage on market and stop fills, and $0.005 per share per side.

The bot's engine (`nb3bot/strategy/nb3v2.py`) re-implements exactly these rules in streaming form. The Pine scripts and the Python Pine mirror (`tests/nb3_reference_engine.py`) differ from the research engine on one documented point. The research engine counts data-outage days as sessions in the 14-session noise average; the Pine mirror skips sessions without a 09:30 bar. The bot follows the research engine, because that is what produced the verified numbers.

No other rules exist in NB3 V2: no regime, trend, volume, news or volatility filter, no trailing or moving of stops. Rules the strategy never defined are listed as unresolved in `nb3bot/README.md`:

- early-close days;
- what to do when data is missing live.

## 2. Exact reproduction of the 675 trades

```
python -m nb3bot verify-parity --data <QQQ 1-minute cache>
```

Report: `nb3bot/validation/reports/parity_report.md`. The reference list was exported from the original research code by `nb3bot/validation/export_reference.py` into `nb3bot/validation/reference_nb3v2_qqq_trades.csv`.

| Item | Result |
|---|---|
| Reference trades | 675 |
| Bot trades | 675 |
| Identical (session, signal bar, direction, entry minute, fill, stop distance, exit minute, exit price, reason, net R, gross R) | **675** |
| Largest difference in any price or R field | **0.0** (bit-identical) |
| Discrepancies | **0** |

## 3. The whole live stack against the backtest

`run_simulated` runs everything the live bot runs on a simulated clock: minute feeds, 5-minute completion with the incomplete-bar guard, the risk guard, the execution manager, the paper broker with broker-side brackets, persistence and the end-of-day rebuild.

With instrument and cost settings equal to the backtest (QQQ ticks, 2-tick slippage, $0.005 per side), over 2025-01-02 to 2025-02-28 (39 sessions):

- **Trades:** 35 of 35 reference trades taken, none extra.
- **Identical:** direction 35/35, entry fill 35/35 (exact), exit reason 35/35.
- **R difference:** mean +0.00003, maximum 0.002. Stops and targets are whole ticks in the bot, while the backtest used unrounded distances.

The automated test `test_full_stack_matches_backtest_trades` repeats this check on 2025-03-03 to 2025-03-14.

## 4. Simulated-live run with the shipped MNQ settings

Run with:

```
python -m nb3bot replay --data <QQQ data> --start 20250102 --end 20250630 --workdir runs/h1 --config nb3bot/config.example.toml
```

Settings:

- **Account:** Topstep 50K Combine rules ($2,000 end-of-day trailing loss limit, $1,000 daily limit).
- **Sizing:** one MNQ, $350 evaluation budget, $1.22 commission, 1 tick of slippage.
- **Prices:** MNQ synthesised as QQQ × 41.3, because no 2025 MNQ minute data was available.

Results are in `nb3bot/validation/replay_2025H1_mnq/` (see section 6).

## 5. Funded risk: resolving the "$250 budget vs ~$275 per MNQ" conflict

Per-contract risk now includes costs: stop ticks × $0.50 + $1.22 commission + 2 ticks of slippage. At Sep–Nov 2026 volatility, one MNQ at the median stop risks about $275, so a $250 budget trades only on calmer days.

`nb3bot/validation/funded_risk_sensitivity.py` repeats the lifecycle simulation with cost-inclusive sizing for funded caps of $250, $300, $350 and $400, keeping $2,000 after payouts. It uses 2,000 lifecycles each, 2025-26 trades with stops scaled to today's volatility, and scenario B (75% of the measured edge). Results are in `funded_risk_sensitivity.csv`.

| Funded cap | Signal days traded | Topstep: chance of profit / median | Lucid | Tradeify |
|---|---|---|---|---|
| **$250** | 32% | **55% / +$1,177** | **59% / +$2,348** | **56% / +$1,100** |
| $300 | 59% | 43% / −$156 | 44% / −$130 | 41% / −$145 |
| $350 | 85% | 45% / −$78 | 46% / −$130 | 43% / −$145 |
| $400 | 92% | 42% / −$156 | 43% / −$130 | 40% / −$145 |

**Decision:** keep $250. A higher cap trades more often but on the volatile days, where the strategy historically earned only +0.08R per trade against +0.25R on other days. That leaves less cushion per dollar risked. The mean profit is sometimes higher with larger caps, but carried by rare large wins, so the median and the chance of profit fall.

Caveats:

- The volatility pattern was measured on the same 2023-26 data. It is a property of the user-specified risk settings, not a new rule added to the strategy.
- No smaller Nasdaq-100 futures contract than MNQ exists at CME. Whether a firm offers any other instrument must be read from its own contract list (`python -m nb3bot check`).

## 6. Automated tests

```
python -m unittest discover -s nb3bot/tests -t .
```

| File | What it covers |
|---|---|
| `test_strategy.py` | The 675-trade parity; signal rules on synthetic data (direction, first signal only, last entry bar, no future data, missing open, snapshot/restore); bracket fill rules (stop first, no target in the entry minute, gap fills worse than the stop). |
| `test_time_risk.py` | NYSE 2026-28 holidays and early closes against the published calendar; DST in March (US vs Europe); contract roll; sizing (never rounded up, skip with reason, costs); loss-limit tracking (end-of-day trailing with lock, intraday trailing, Topstep payout); every risk-guard check vetoing; edge stop rules. |
| `test_execution.py` | Bracket entry to target; duplicate signal blocked; lost acknowledgement looked up by tag, never resent; rejection; missing bracket replaced; protection failure leads to flatten; 15:55 flatten with no orphans; crash and restart mid-trade; unknown position flattened and halted; orphan orders cancelled; kill switch; broker outage; stop gap. |
| `test_integrations.py` | ProjectX request bodies match the official documentation (brackets, customTag, sides); Position-Brackets rejection; order timeout leads to UncertainOrderState with no retry; read retries and re-login; parsing; missing credentials; data feed gaps, bad bars and the ratio check; DELAYED data detection; authorization gating; config validation; kill file; dashboard token protection. |
| `test_app.py` | The whole bot end to end: signal, trade and 15:55 exit with MNQ settings; data outage on the signal bar blocks entry; kill switch mid-trade; crash and restart mid-trade with no duplicate; funded budget too small leads to skip; loss-limit headroom blocks; full stack vs backtest on real data. |

## 7. External API sources

The ProjectX Gateway API documentation was read on 2026-11-17. It covers authentication, accounts, contracts, bars, order place/search/cancel, positions, trades, realtime enums and rate limits:

- <https://gateway.docs.projectx.com/docs/api-reference/order/order-place/>
- <https://gateway.docs.projectx.com/docs/getting-started/authenticate/authenticate-api-key/>
- <https://gateway.docs.projectx.com/docs/getting-started/rate-limits/>
- <https://gateway.docs.projectx.com/docs/realtime/>

The NYSE holiday calendar was taken from <https://www.nyse.com/markets/hours-calendars> on 2026-11-17.
