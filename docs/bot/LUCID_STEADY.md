# Simulated LucidFlex 50K, "steady" setting (`lucid_flex_50k_steady`)

**Short version:**

* This profile is NB3 V2 with the exits and payout policy that got the most simulated LucidFlex accounts
  paid (research rounds 5-6: `backtest/RESULTS_5.md`, `backtest/RESULTS_6.md`).
* It runs **only in simulation**: the program's own paper broker, with MNQ prices simulated from free
  QQQ data. Nothing is sent to Lucid.

## What changes compared with NB3 V2

| | NB3 V2 (default) | Lucid steady profile |
|---|---|---|
| Entry signal | 5-minute close outside the noise band | **unchanged** |
| Stop | 0.30 x previous daily ATR | **unchanged** |
| Target | 3R | **1.5R** |
| Trades a day | 1 | **up to 2**: after the first trade closes, the next band signal (entry after the exit minute, before 14:55) |
| Risk per trade | $350 evaluation / $250 funded | **$350 / $350**: 1 MNQ at today's volatility, skipped if one MNQ risks more |
| Account rules | Topstep 50K | **LucidFlex 50K**, including the funded scaling plan (20 / 30 / 40 micros) |
| Payouts | not tracked | the dashboard shows when you are eligible and how much to request (keep $500 above the $50,100 loss limit) |
| 200-trade edge stop | mean below +0.05R | mean below 0R |

**Proof:** the bot reproduces the research trade for trade. In a 2023-26 replay all **1,097 trades are
identical** (`nb3bot/tests/test_lucid_steady.py`, reference `nb3bot/validation/reference_lucid_steady_qqq_trades.csv`).

## What to expect (research, today's volatility, one $130 account)

* **Chance of at least one payout within 12 months:**
  * 41% if 2023-26 repeats;
  * about 30% if markets are like 2016-22;
  * 19-23% with half the edge.
* **Typical first payout:** about $730 before Lucid's 10%, about $630 to you.
* **One paid account:** typically delivers about $850-$1,060 in total.
* **Cost per paid account:** about $300-$400 spent on accounts.

These are simulations of past data, not promises.

## Start it on your Mac

1. Install once: `bash install_mac.sh` (see [TRADINGVIEW_DEMO.md](TRADINGVIEW_DEMO.md)).
2. Double-click **`start_lucid_steady.command`**.
   * It creates `nb3bot_lucid.toml` from this profile, checks that it cannot send orders, and starts the
     bot.
   * The dashboard opens at <http://127.0.0.1:8766>.
   * Without Alpaca keys it offers the offline demo.
3. **After the simulated evaluation passes**, the bot halts and says so. Then:
   * set `risk.phase = "funded"` and `account.preset = "lucid_flex_50k_funded"` in `nb3bot_lucid.toml`;
   * delete the `state_lucid` folder for a fresh funded account.
4. **When the dashboard says "Payout ELIGIBLE":**
   * The bot never requests payouts. With a real account you would request the shown amount on Lucid's
     site.
   * In the simulation, record it so the loss limit stays right:
     ```
     .venv/bin/python -m nb3bot record-payout --config nb3bot_lucid.toml --amount 750 --floor-after 50100
     ```

The TradingView NB3 V2 indicator still shows the same entry signals; it does not show the 1.5R target or
the second trade.
