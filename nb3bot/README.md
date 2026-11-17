# NB3 V2 automated futures bot (`nb3bot`)

The researched NB3 V2 strategy as a working, automated trading system:

- **Signals:** QQQ noise-band breakout, first signal of the day, 1:3 bracket, flat by 15:55 New York.
- **Execution:** Micro E-mini Nasdaq-100 (MNQ) futures.
- **Order path:** the ProjectX Gateway API (TopstepX), or a built-in paper broker.

**Live order sending is OFF.** The shipped configuration cannot send an order to any account. Practice-account orders and real (evaluation or funded) orders each need a config switch, a matching command-line mode, a typed authorization, and a passing parity report. See [docs/bot/OPERATING_MANUAL.md](../docs/bot/OPERATING_MANUAL.md).

## What is in here

| Module | What it does |
|---|---|
| `strategy/nb3v2.py` | The NB3 V2 engine, bar by bar. It reproduces all 675 verified backtest trades exactly (`validation/reports/parity_report.md`). |
| `strategy/bracket.py` | The backtest's fill model: next-bar-open entry, stop checked first, gap fills, no target fill in the entry minute, 15:55 exit. |
| `data/` | Minute-bar feeds: Massive/Polygon REST for QQQ, ProjectX History for MNQ, and replay. Also missing-bar, bad-bar, delayed-feed and QQQ/MNQ consistency checks. |
| `timeutil.py` | New York session clock with DST, the NYSE holiday and early-close calendar (matches NYSE's published 2026–28 calendar), and Zagreb display time. |
| `contracts.py` | MNQ/NQ specifications and the quarterly roll schedule. |
| `risk/sizing.py` | Whole-contract sizing. Per-contract risk includes commission and slippage; quantities are never rounded up; a trade is skipped with a recorded reason. |
| `risk/account.py` | Prop-firm loss-limit tracking: end-of-day trailing with real-time breach, intraday trailing, static floors, locks, Topstep's after-payout rule, presets for Topstep, Lucid and Tradeify. |
| `risk/guard.py` | About 20 pre-trade checks (data, broker, flat, one trade a day, size, firm headroom and daily limit, personal limits, stop rules), each logged. |
| `execution/manager.py` | Entry with broker-side OCO bracket, idempotent `customTag`, fill confirmation, bracket verification, stop re-placement or flatten, 15:55 flatten, orphan cleanup, reconciliation, kill switch. |
| `broker/paper.py`, `broker/projectx.py` | Paper broker (with failure injection), and the ProjectX adapter built from the official documentation. |
| `storage.py`, `alerts.py` | SQLite state for crash recovery, an append-only JSON-lines audit log, and Telegram, webhook and e-mail alerts. |
| `app.py` | The runtime loop that ties everything together. |
| `dashboard/` | Local web dashboard with New York and Zagreb time, risk checks, account room, trades, alerts and a kill button. |
| `replay/` | Historical replay, the automated parity check, and simulated-live runs of the whole stack. |
| `tests/` | 70 automated tests, including the 675-trade parity, full-stack replays and the demo profile. |
| `profiles/` | Ready-made configurations, such as `tradingview_50k_demo` (simulated $50,000 account). |

## Simulated $50,000 demo on a Mac

`bash install_mac.sh`, then double-click `start_demo.command`. That uses the `tradingview_50k_demo` profile:
free Alpaca QQQ data, simulated MNQ prices and the bot's own paper broker. Without data keys it offers an offline
demo on synthetic prices. TradingView is for viewing charts only: its terms forbid automated trading on its data,
and it has no order API for its Paper Trading account. Details: [docs/bot/TRADINGVIEW_DEMO.md](../docs/bot/TRADINGVIEW_DEMO.md).

## Quick start

```
python -m pip install -r nb3bot/requirements.txt
python -m nb3bot verify-parity --data <QQQ 1-minute data>
python -m unittest discover -s nb3bot/tests -t .
python -m nb3bot replay --data <QQQ data> --start 20250102 --end 20250630 --workdir runs/h1
```

Then follow [docs/bot/INSTALL.md](../docs/bot/INSTALL.md) and the operating manual.

## Known limitations and unresolved issues

These are listed honestly so nothing is silently assumed.

1. **Early-close sessions.** The day after Thanksgiving, Christmas Eve and some July 3rds close at 13:00. NB3 V2 defines no rule for them, so the bot does not trade those days. The backtest had a single such day, Nov 29, 2024, with data only to 13:00.
2. **Real-time QQQ data.** The validated design takes signals from QQQ. That needs a real-time US-stock feed; the Massive (formerly Polygon) adapter is built and tested on recorded responses, but not against a live key. If the provider reports `DELAYED`, the bot refuses to trade. The alternative `signal_source = "MNQ"` matched QQQ's signal bar on 97% and the direction on 100% of 35 test days, but it is not the validated source.
3. **ProjectX behaviour still to confirm on a practice account:**
   - whether bar timestamps are bar starts (assumed);
   - that bracket ticks are measured from the fill price (documented, not yet observed);
   - the account must be in **Auto OCO Brackets** mode.
4. **REST polling, not streaming.** The bot uses ProjectX REST polling, within the documented rate limits; the SignalR streaming hubs are not used yet. Fills and exits are seen within seconds. Protection does not depend on polling, because the stop and target are broker-side.
5. **Lucid and Tradeify.** These firms are not integrated: no official order API for their platforms was verified. They would need a separate adapter, for example a NinjaTrader 8 strategy, which is not built.
6. **Paper fills follow the backtest assumption** (next 1-minute bar open), not live quotes. Real fills will differ; compare them during practice-account testing.
7. **Stop rounding.** Stops and targets are rounded to whole ticks, so per-trade R differs from the backtest by at most about 0.002R. The entries, directions and exit reasons were identical in the full-stack replay.
8. **History definition.** The verified backtest counts data-outage days as sessions in the 14-day noise average; the Pine mirror skips them. The bot follows the backtest. Live, every exchange trading day is a session, rebuilt each evening from re-downloaded final data.
9. **TopstepX API:** costs $29/month, works on evaluation and Express Funded accounts but not on Topstep's Live Funded Account, and must run on your own computer (no VPS or VPN).
10. **No news filter.** NB3 V2 has none, and the bot adds none. Check your firm's news-trading rules.
11. **Your request was cut off** after "4.4 … Maximum trade risk". Everything visible was implemented; send the rest if more was intended.
