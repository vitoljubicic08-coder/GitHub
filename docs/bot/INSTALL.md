# Installing the NB3 V2 bot

> **On a Mac, for the simulated $50,000 demo, the short way is:** `bash install_mac.sh`, then double-click
> `start_demo.command`. See [TRADINGVIEW_DEMO.md](TRADINGVIEW_DEMO.md). The steps below are the manual route.

The bot is a Python program that runs on **your own computer**. Topstep forbids running automated trading from a VPS or through a VPN, so do not use one. Windows 10/11, macOS and Linux all work.

## 1. Install Python 3.11 or newer

- **Windows:** download it from <https://www.python.org/downloads/>.
  - Tick **"Add python.exe to PATH"** in the installer.
  - Open a new **Command Prompt** and check: `python --version`
- **macOS:** `brew install python@3.12`, or use the python.org installer. Check with `python3 --version`.

In the commands below, Windows uses `python` and macOS/Linux use `python3`.

## 2. Get the code

```
git clone https://github.com/vitoljubicic08-coder/GitHub.git nb3
cd nb3
git checkout claude/sip-orb-precision-v1-z3krh0
```

You can also download the branch as a ZIP from GitHub and unzip it.

## 3. Create an isolated environment and install the packages

```
python -m venv .venv
.venv\Scripts\activate            (Windows)
source .venv/bin/activate         (macOS/Linux)
python -m pip install -r nb3bot/requirements.txt
```

## 4. Check that the code works (no accounts needed)

```
python -m unittest discover -s nb3bot/tests -t .
```

- **Expected:** `OK`.
- **Skipped tests:** two tests need the research QQQ data and are skipped without it.
- **Running them:** point `NB3_QQQ_DATA` at a folder of `market_*.npz` files, or use a CSV (step 5).

## 5. (Optional) Re-run the 675-trade parity check

It needs the same QQQ 1-minute data the research used. A CSV works: columns `timestamp,open,high,low,close,volume`, with the timestamp in ISO format including the UTC offset.

```
python -m nb3bot verify-parity --data path/to/qqq_minutes.csv
```

The result is written to `nb3bot/validation/reports/parity_report.md`. Practice and live modes refuse to start unless this report says PASS. A passing report from this research run is already in the repository.

## 6. Create your configuration

```
python -m nb3bot init-config nb3bot.toml
```

Open `nb3bot.toml` in a text editor. Every setting is explained inside the file. For now, leave `mode = "paper"` and `broker.name = "paper"`.

## 7. Store credentials as environment variables (never in the config file)

| Variable | What it is | Where you get it |
|---|---|---|
| `PROJECTX_USERNAME` | Your TopstepX platform user name (not your e-mail) | Your TopstepX login |
| `PROJECTX_API_KEY` | API key | TopstepX → Settings → API (needs the $29/month API subscription) |
| `MASSIVE_API_KEY` | Real-time QQQ data key | massive.com (formerly Polygon.io); needs a plan with **real-time** US stocks |
| `NB3_TELEGRAM_TOKEN` | Optional alert bot token | Telegram @BotFather |

**Windows** (Command Prompt, then open a NEW window):

```
setx PROJECTX_USERNAME "your.username"
setx PROJECTX_API_KEY "paste-the-key"
setx MASSIVE_API_KEY "paste-the-key"
```

**macOS/Linux:** add `export PROJECTX_USERNAME="..."` lines to `~/.zshrc` or `~/.bashrc`.

## 8. Read-only connection check (sends no orders)

```
python -m nb3bot check --config nb3bot.toml
```

It shows:
- your active ProjectX accounts and their IDs (put yours in `broker.account_id`);
- the MNQ contract the calendar expects and the one the broker lists;
- recent MNQ bars;
- whether the QQQ feed is real-time.

## 9. In the TopstepX platform

Go to **Settings → Risk Settings**, switch **Position Brackets** to **Auto OCO Brackets**, then set `broker.auto_oco_brackets_confirmed = true`. The bot attaches a stop and target to every entry. In "Position Brackets" mode the platform rejects those orders, and the bot would report the rejection.

## 10. Next

Follow the staged plan in the [operating manual](OPERATING_MANUAL.md): replay, then paper, then practice account, and only then a real evaluation.
