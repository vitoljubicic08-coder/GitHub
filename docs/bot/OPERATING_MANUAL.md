# NB3 V2 bot — operating manual (beginner friendly)

## 1. What the bot does, in plain words

Every US trading day the bot watches QQQ, the Nasdaq-100 ETF, from 09:30 to 16:00 New York time. That is 15:30–22:00 in Zagreb most of the year. During the few weeks when the US and Europe change clocks on different dates, the gap is 5 hours instead of 6. The dashboard always shows both times.

It looks for **one** event per day: QQQ closing a 5-minute candle unusually far above or below the day's opening price. "Unusually far" means beyond the average move at that time of day over the last 14 sessions. This is the NB3 V2 strategy exactly as it was backtested.

When that happens (about 4 days in 5), the bot:

1. **Checks:** roughly 20 safety checks pass or fail. Is the data complete? Is the broker connected? Is the account flat? Is there enough room above the prop firm's loss limit? Are you within your daily, weekly and total loss limits?
2. **Sizes:** works out how many MNQ contracts fit your risk budget. Usually one; zero means the trade is skipped and the reason is recorded.
3. **Enters:** buys or sells MNQ at market, with a **stop-loss** and a **take-profit** attached at the broker:
   - the stop is 0.30 × yesterday's daily range average (ATR);
   - the target is three times the stop distance.
4. **Verifies:** checks the stop and target really exist at the broker; if the stop is missing it places one, and if it cannot, it closes the trade.
5. **Exits at 15:55:** if neither the stop nor the target was hit, it closes the trade and cancels leftover orders.
6. **Records:** logs everything, updates the account's loss-limit tracking, and sends you a message.

It never trades more than once a day, never adds to a position and never moves the stop or target. The tested strategy does none of these things.

**What it cannot promise:**

- **Stops are not guaranteed prices.** In a fast market or a gap a stop can fill worse than planned. The research showed a stop filling at −2R and worse.
- **The edge is not guaranteed.** The research found a modest one (about +0.2R per trade, 45–48% winners), with long losing runs being normal: up to 7 losses in a row in the backtest.
- **Paper or simulated results are not real fills.**

## 2. The modes, from safe to real

| Mode | What it does | Real orders? | What you need |
|---|---|---|---|
| `replay` | Runs the whole bot over past data in seconds | No | QQQ history |
| `paper` | Runs live on real-time data; fills are simulated by the bot | No | ProjectX API (for MNQ data) + real-time QQQ |
| `practice` | Sends orders to a **practice** (fake money) account | Yes, to a practice account | Practice switch + `authorize --mode practice` |
| `live` | Sends orders to your **evaluation or funded** account | Yes | Live switch + `authorize --mode live` + passed stages |

Move one step at a time, using the pass criteria in section 7.

## 3. Starting and stopping

```
python -m nb3bot run --config nb3bot.toml --mode paper
```

- The mode on the command line must match `bot.mode` in the file, so you cannot start live by accident.
- On first start it downloads about a year of history to prepare the noise band and the ATR. That takes a few minutes, once.
- Open the dashboard in your browser: <http://127.0.0.1:8765>.
- **Arming:** in paper mode the bot is armed automatically. In practice and live mode it starts DISARMED and only takes entries after you run:
  ```
  python -m nb3bot arm --config nb3bot.toml
  ```
- **Stopping:** press **Ctrl+C**. If a position is open, the bot **closes it** before exiting. Use `--leave-position` only if you want the broker-side stop and target to stay. In that case remember that **nobody will close it at 15:55**.

Leave the computer on with sleep disabled during market hours, and keep a stable internet connection.

## 4. The dashboard

- **Top line:** mode (green paper, orange practice, red LIVE), ARMED or DISARMED, New York and Zagreb time.
- **Safety:** kill switch, halts (reasons the bot stopped taking entries), whether order sending is authorized, broker errors, and whether the bot's view matches the broker.
- **Account and risk:** balance, equity, the firm's loss-limit floor, and **room to the floor**, which turns red below $700.
- **Today:** the session, the contract (for example MNQZ26), the signal if any, and whether it was traded.
- **Risk checks:** every check for today's signal with pass or fail and the numbers. This tells you exactly why a signal was or was not traded.
- **Performance:** the bot's own trades, mean R, win rate, P&L and the **edge monitor** (section 8).
- **Emergency controls:** the token is in `state/dashboard_token.txt`. **KILL** cancels all orders, closes all positions and disarms. **Disarm** only stops new entries.

## 5. Daily routine

| When (Zagreb) | What to do |
|---|---|
| Before 15:25 | Start the bot (or check it is running). Dashboard: engine warm, contract OK, no halts, room to the floor sensible. |
| 15:30–20:55 | Nothing. The bot trades on its own. You get messages for signals, fills and exits. |
| ~21:55 | The bot flattens at 15:55 New York. Check the dashboard shows flat and no open orders. |
| After 22:05 | The bot rebuilds tomorrow's history from final data and logs the day. Look at the day's result if you like. |

Weekly: `python -m nb3bot report --config nb3bot.toml` prints the performance table.

## 6. What to do when…

| Situation | What the bot does | What you do |
|---|---|---|
| Market data stops or arrives late | No new entries; alert "Market data error" or "NOT traded: … missing". An open trade keeps its broker-side stop and target. | Check your internet and the data provider. The bot resumes by itself when data is complete. |
| Broker connection drops | No new entries; it keeps retrying and reconciles when back. | Check TopstepX status and your internet. If a position is open and the outage is long, check it in the platform. |
| "bracket stop missing" alert | It placed its own stop and target. | Check in the platform that exactly one stop and one target exist. |
| "could not place protective stop … CLOSING" | It closed the position. | Check the platform shows flat. Find out why the stop was refused (wrong bracket mode, account violation). |
| "unknown position found" | It closed it and halted. | Did you trade by hand? Don't, in the bot's account. Then `clear-halts`. |
| "Contract check failed" | No entries that day. | Usually the quarterly roll. Compare `check` output with the platform. Adjust `roll_days_before_expiry` if needed. |
| Early-close day (13:00 close) | It does not trade. | Nothing. |
| Edge monitor says PAUSE or STOP | It halts entries. | Read section 8. Don't override without thinking. |
| You need to stop everything NOW | — | Dashboard **KILL**, or `python -m nb3bot kill --config nb3bot.toml`, or close the position in the platform. |
| The computer crashed mid-trade | The broker-side stop and target still protect the trade. On restart the bot reads its database, asks the broker what happened and continues. It never re-enters the same day. | Restart the bot as usual and check the dashboard. |
| You took a payout | — | Record it, for example: `python -m nb3bot record-payout --config nb3bot.toml --amount 1000 --floor-after 0`. Topstep Express sets the loss limit to a $0 balance after a payout, hence `--floor-after 0`; use no `--floor-after` where withdrawals don't move it. |

After a kill: `clear-kill`, find the cause, then `arm` again.

## 7. Stages before real money (pass criteria fixed in advance)

1. **Replay** (done in the research, repeatable): parity PASS, all tests OK.
2. **Paper, at least 30 trading days:**
   - the bot acted on 100% of the signals the replay of the same days finds, in the same direction;
   - it entered within 10 seconds of the candle close on at least 95% of signals;
   - zero unprotected, duplicate or overnight positions;
   - every alert arrived.
3. **Practice account, at least 20 trading days:**
   - Stage 2 criteria hold on real platform fills;
   - entry slippage is 1 tick or less (median) and 3 ticks or less (95th percentile);
   - every bracket is present within 5 seconds;
   - the 15:55 flatten works every day;
   - one deliberate kill test and one deliberate restart test, both clean.
4. **One real evaluation (start with the cheapest), one MNQ:**
   - `risk.phase = "evaluation"`, $350 per trade;
   - get written confirmation from the firm that your automation is allowed.
5. **Funded:**
   - set `risk.phase = "funded"` (budget $250) and the matching account preset;
   - record every payout;
   - keep at least $2,000 above the loss limit when withdrawing.

These stages test **execution**. 25–50 trades are far too few to prove the edge.

## 8. The edge monitor (pre-registered stop rules)

The bot compares its own results with what the research expects. Per-trade results vary a lot: a standard deviation of about 1.4R.

- **PAUSE** if the average is below −0.13R after 50 trades.
- **STOP** if the average is below −0.04R after 100 trades, or below +0.05R after 200 trades.

These limits were fixed before trading. Don't change them after a bad week.

## 9. About risk per trade (and the "$250 vs $275" question)

- **One MNQ's risk:** at today's volatility one MNQ risks about $275 including costs, but this varies daily from about $150 to $370.
- **Evaluation ($350):** almost every signal can be traded with one contract.
- **Funded ($250):** the bot **skips** signals on days when one contract would risk more than $250, about two days in three at today's volatility. This is intentional.
  - A follow-up simulation, with costs included, compared $250, $300, $350 and $400 funded caps. **$250 gave the highest chance of profit (55–59% vs 41–46%) and the best median.** The days it skips are the high-volatility days, where the strategy historically earned least.
  - Details are in [VALIDATION.md](VALIDATION.md).
- **Never** raise the risk to win back losses, and **don't** increase `max_contracts` above 1 until the paper and practice stages pass.

## 10. Files the bot creates

| Path | What it is |
|---|---|
| `state/bot.sqlite` | State: open trade, intents, trades, account tracking, events. **Back it up; don't edit it.** |
| `state/KILL` | Exists while the kill switch is on. |
| `state/AUTHORIZE_*.json` | Your typed authorizations. |
| `state/dashboard_token.txt` | Token for the dashboard buttons. |
| `logs/audit-YYYYMMDD.jsonl` | Every decision, order and fill, one JSON line each. |
