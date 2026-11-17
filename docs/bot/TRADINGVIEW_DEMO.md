# $50,000 demo with TradingView on a Mac (`tradingview_50k_demo`)

**Short version:**

- The bot cannot trade inside TradingView's Paper Trading account. TradingView has no API for that, and its terms forbid automated trading on its data, alerts or webhooks.
- So the demo runs the bot's own simulated $50,000 account, on legally licensed free QQQ data from Alpaca.
- You use TradingView only to *look at* the same signals on a chart.
- **The demo's trades will not appear in TradingView.**

## 1. What TradingView supports (checked 2026-11-17)

| Question | Answer | Source |
|---|---|---|
| $50,000 starting balance in Paper Trading | **Yes, manually.** "Customize your settings: set initial balance, commissions, and account currency." Resetting the account deletes its history. | [tradingview.com/trading](https://www.tradingview.com/trading/), [support: account currency / reset](https://www.tradingview.com/support/solutions/43000480903-how-to-change-the-account-currency-in-paper-trading/) |
| MNQ futures | Charts: yes (`CME_MINI:MNQ1!`). Whether its Paper Trading account accepts MNQ orders is **not stated** in the official pages I found. | [MNQ1! symbol page](https://www.tradingview.com/symbols/CME_MINI-MNQ1!/) |
| Placing orders from a program | **No official API found.** TradingView's Broker API is for brokers building a trading terminal inside TradingView's charting library, not for users sending orders into Paper Trading. | [Charting Library: Broker API](https://www.tradingview.com/charting-library-docs/latest/tutorials/implement-broker-api/) |
| Automatic position management, stop-loss, take-profit | Only by hand in the Paper Trading panel. Pine strategies run in the Strategy Tester's own simulator, which is separate from the Paper Trading account. | [Pine Script: strategies](https://www.tradingview.com/pine-script-docs/concepts/strategies/) |
| External Python bot connection | **No.** | — |
| Alerts and webhooks | A webhook only *sends a notification* (HTTP POST) to a URL you choose. It needs a paid plan and 2-factor authentication, and it does not execute orders in TradingView. | [How to configure webhook alerts](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/) |
| Using TradingView data, alerts or webhooks to drive a bot | **Prohibited** (Terms of Use, Section 3) | Quoted below |

TradingView's Terms of Use, Section 3 ([tradingview.com/policies](https://www.tradingview.com/policies/)) forbid "non-display usage", explicitly including any product that:

> "Utilizes, repurposes, or relies upon TradingView's market data, including but not limited to charts, alerts, webhooks, and any forms of information provided by TradingView, for any form of automated trading, algorithmic decision-making, or any other non-display purposes."

**Consequence for the design.** The bot never reads anything from TradingView, and nothing scrapes it. TradingView is used only to display charts for you, and the NB3 V2 indicator there is for comparing by eye. A webhook bridge from TradingView alerts to the bot would also violate those terms, so it was not built.

## 2. What the demo is

```
Alpaca free market data (official API) ──► NB3 V2 engine (exact, 675/675 parity) ──► risk guard
   QQQ 1-minute bars                                                                    │
                                                         paper broker (this program) ◄──┘
                                                         $50,000 simulated Topstep-style account
                                                         MNQ prices SIMULATED = QQQ × 41.3
                                                                     │
                                                         dashboard  http://127.0.0.1:8765
```

- **QQQ data:** Alpaca's free Basic plan ([plans](https://docs.alpaca.markets/us/docs/about-market-data-api)) provides two feeds:
  - real-time bars from **IEX**, one exchange carrying about 2.5% of volume, used live;
  - consolidated **SIP** bars from all exchanges, the same kind of data the backtest used, but only once they are at least 15 minutes old.
  - **How the bot uses them:** IEX live; SIP for the one-off history download and the evening rebuild.
  - **If your account is refused SIP:** Alpaca's documentation says paper-only accounts may get IEX data only. The bot then falls back to IEX and shows a note on the dashboard.
- **MNQ prices:** there is no free licensed real-time CME futures feed, so MNQ prices are **simulated** as QQQ × 41.3, rounded to the 0.25 tick. In the research, QQQ and NQ 5-minute returns correlated at 0.98, and per-trade results at 0.996. The ratio drifts slowly (40.9–41.5). You can set `synthetic_ratio` to TradingView's MNQ1! price ÷ the QQQ price.
- **Fills:** the paper broker fills like the backtest:
  - entry at the next 1-minute open plus 1 tick of slippage;
  - the stop checked first, with gap fills at the open;
  - the target as a limit order;
  - the 15:55 exit at the last price;
  - $1.22 commission per round turn.
- **Single-exchange gaps:** IEX has no bar for a minute without an IEX trade. The bot treats that as normal (`allow_empty_minutes`). It refuses entries only if no new bar has arrived for 3 minutes.
- **Signal agreement:** every evening the bot re-downloads the day's consolidated bars. It then checks whether they give the same signal as the live IEX bars. The dashboard counts the days that agree and the days that differ, which tells you how far the free data departs from the validated setup.

## 3. The simulated account

Profile: `nb3bot/profiles/tradingview_50k_demo.toml`. Every value can be changed in your copy, `nb3bot_demo.toml`.

| Parameter | Setting |
|---|---|
| Starting balance | $50,000 (simulated) |
| Trading instrument / signal instrument | MNQ (simulated prices) / QQQ |
| Strategy | NB3 V2, unchanged: the stop is never altered to make a trade fit |
| Profit target | $3,000, and the best day must be at most 55% of profit (Topstep's consistency target) |
| Maximum loss | $2,000, trailing the **highest end-of-day balance**, breached **in real time** including open P&L, stops trailing at $50,000 |
| Daily loss limit | $1,000 |
| Risk budget | $350 per trade in evaluation, $250 funded. Commission and slippage count in the per-contract risk, and the trade is **skipped** if one MNQ costs more. |
| Size | Whole MNQ contracts only, at most 1 |
| Costs | $1.22 per round turn, 1 tick of slippage per side |
| Real orders | Disabled. `safety-check` must say "SIMULATION ONLY", or the launcher refuses to start. |

**Why Topstep's rules.** The drawdown method is reproduced from Topstep's own help centre (checked 2026-11-17):

- [Maximum Loss Limit](https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit): "rises as your end-of-day balance grows… monitored in real time… both realized and unrealized P&L count";
- [Consistency](https://help.topstep.com/en/articles/8284208-what-is-the-consistency-target): 55%;
- [Combine parameters](https://help.topstep.com/en/articles/8284197-trading-combine-parameters).

Other firms differ (Lucid and Tradeify presets exist in `nb3bot/risk/account.py`).

**When the target is reached** the bot halts and says so. To continue in funded mode, set `risk.phase = "funded"` (the $250 budget) in `nb3bot_demo.toml`. Optionally also set `account.preset = "topstep_xfa_50k"`: Topstep's funded account starts at a $0 balance by its own convention. Then delete the `state_demo` folder for a fresh account.

## 4. What you do on your Mac (about 15 minutes)

1. **Get the project:**
   - With git:
     ```
     git clone https://github.com/vitoljubicic08-coder/GitHub.git nb3
     cd nb3
     git checkout claude/sip-orb-precision-v1-z3krh0
     ```
   - Or download <https://github.com/vitoljubicic08-coder/GitHub/archive/refs/heads/claude/sip-orb-precision-v1-z3krh0.zip>, unzip it, and open Terminal in that folder.
2. **Install:**
   ```
   bash install_mac.sh
   ```
   - **What it does:** it uses Python 3.11 or newer, makes a private `.venv`, installs the packages, creates `nb3bot_demo.toml`, runs the safety check and the self-tests, and offers to save your Alpaca keys in the macOS Keychain. No `sudo`, nothing installed outside the folder.
   - **No suitable Python:** it tells you to install it from python.org (or `brew install python@3.12`).
3. **Free Alpaca data keys** (only for the live demo):
   - Sign up at <https://alpaca.markets>, choose the **paper** account, and generate API keys. No deposit is needed for paper; non-US residents can use paper-only accounts.
   - When `install_mac.sh` asks, paste the key ID, then the secret. The secret goes into the Keychain prompt with hidden typing.
4. **Start:** double-click **`start_demo.command`**.
   - **The first time**, macOS may block it because it came from the internet. Right-click it, choose **Open**, then **Open** again.
   - **What it does:** it checks the installation, shows the safety summary, reads your keys from the Keychain, checks the data connection and starts the bot. It opens the dashboard in your browser at <http://127.0.0.1:8765> once it is ready. The first start downloads about a year of history, which takes about 2 minutes.
   - **Without keys**, it offers the **offline demo on synthetic prices** instead. That shows the whole system working, but its numbers mean nothing.
5. **Leave it running** on market days, 15:30–22:00 Zagreb time. Turn off sleep, or set the computer not to sleep while plugged in. Stop it with Ctrl+C in its window.

## 5. Comparing on TradingView (optional, by eye)

1. **Open the chart:** in TradingView, open **NASDAQ:QQQ** on the **5-minute** timeframe with regular trading hours.
2. **Add the indicator:**
   - Open the **Pine Editor**, choose **Create new**, and replace the template with the full text of `nb3_breakout_v2_indicator.pine` from the project folder.
   - Press Cmd+S, then **Add to chart**. These steps follow TradingView's [How to create a new script](https://www.tradingview.com/support/solutions/43000711497-how-to-create-a-new-script/).
3. **Compare:** a green arrow (BUY) or red arrow (SELL) should appear on the same 5-minute bar as the bot's signal on its dashboard.
   - **Why they can differ:** TradingView draws on consolidated data, while the bot uses IEX live, so occasional differences are expected.
   - **Where to look:** the dashboard's "Live vs final-data signals" panel counts them against consolidated data.
4. **Watching MNQ:** you can watch `CME_MINI:MNQ1!` for context. Unless you buy CME real-time data on TradingView, its futures quotes may be delayed.

You may also create a $50,000 TradingView Paper Trading account by hand to mirror trades yourself. The bot cannot place them there.

**LucidFlex setting:** a second launcher, `start_lucid_steady.command`, runs the same kind of simulation with LucidFlex 50K rules. It uses the payout-optimized "steady" setting: a 1.5R target and up to 2 trades a day. See [LUCID_STEADY.md](LUCID_STEADY.md).

## 6. Limits of this demo (read before judging results)

- **Data source:** live signals come from one exchange (IEX), not the consolidated data of the 675-trade validation. Use the agreement panel to see how often that changes the signal.
- **Simulated MNQ prices:** they are not real futures quotes, and the futures basis is ignored.
- **Fills:** paper fills follow the backtest's assumptions, not a real order book.
- **Early-close days:** the bot does not trade the 1:00 pm sessions (NB3 V2 has no rule for them).
- **What a good result means:** a good result here shows the machinery works and the edge is not obviously gone. It does not prove the edge. The research needs about 100+ trades for that.
- **Next step:** moving to a ProjectX practice account means real futures data and real platform fills. See the [operating manual](OPERATING_MANUAL.md).
