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

## Near the loss limit: keep trading (Lucid profile only)

* **Other profiles:** by default the bot halts when a trade's worst case would leave less than $100 above
  the firm's limit.
* **Why not for Lucid:** on a LucidFlex account that froze every account for good. A frozen account cannot
  recover, and failing it costs nothing beyond the $130 fee.
* **So:** this profile sets `halt_near_limit = false` and keeps trading while the account is above the
  limit.
* **Effect:** in the 10-year backtest (`backtest/RESULTS_10Y_STEADY.md`), net cash nearly doubled: +$15,691
  vs +$8,043 at historical volatility, and +$13,008 vs +$3,609 at today's.

## Daily limits (both profiles)

| Limit | Lucid steady | When it acts |
|---|---|---|
| **Daily loss** | **-$800** (the firm's daily limit if lower; LucidFlex here has none) | **Before each entry:** today's P&L minus the new trade's worst case must stay above it. **While a trade is open:** if today's P&L including the open trade reaches it, the bot closes the trade and takes no more entries today (`flatten_on_daily_loss`). |
| **Best-day cap** (evaluation only) | **$1,200** = 40% x $3,000 | No entry whose full target could push today above it, so Lucid's consistency rule never delays passing. Off in the funded phase (no consistency rule there). |
| **Daily profit cap** | **off** (`max_daily_profit = 0`) | Optional: once today is up that much, no new entries; `flatten_on_daily_profit` also closes the open trade. |

**Why the profit cap is off:**
* Over 10 years, second trades taken after a winning first trade averaged +0.12R (2016-22) and
  +0.01R (2023-26), so stopping after a good day would not have helped.
* The worst day in 10 years was two full losses, about -2.1R, roughly -$610 at 1 MNQ. That is inside
  the $800 limit.

These limits come on top of the firm's trailing loss limit and your weekly and total limits, which the
bot already checks before every trade. The start-up safety summary and the dashboard show them.

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

## TradingView version

**File:** `nb3_lucid_steady_strategy.pine` (Pine Script v5) shows the same setting on a QQQ 5-minute chart.
It has:
* the NB3 signal;
* the 1.5R target and the second trade;
* MNQ-sized trades (the Strategy Tester trades the equivalent QQQ shares);
* the daily limits and LucidFlex account tracking (loss limit, evaluation pass, payouts);
* alerts for trading by hand.

**To add it:** in the Pine Editor, create a new script (or open your NB3 V2 strategy), select all, paste the
file, save, then **Add to chart**.

**Notes:**
* It was syntax-checked with a Pine parser (`pynescript`) but not compiled in TradingView here.
* TradingView's fills and 5-minute account checks are approximations of the bot's minute-by-minute model.
* TradingView's terms do not allow its alerts or data to drive automated trading.
