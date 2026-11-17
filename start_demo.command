#!/bin/bash
# NB3 V2 bot - double-click to start the SIMULATED $50,000 demo (profile tradingview_50k_demo).
# Nothing here can send an order: the safety check below refuses to start otherwise.
cd "$(dirname "$0")" || exit 1
PY=.venv/bin/python
DASH="http://127.0.0.1:8765"

pause() { echo; read -r -p "Press Enter to close this window." _ || true; }
fail() { echo; echo "ERROR: $*"; pause; exit 1; }
open_when_up() {      # open the dashboard in the browser as soon as it answers (warm-up can take ~2 minutes)
  for _ in $(seq 1 150); do
    sleep 2
    if curl -s -o /dev/null "$DASH/api/status"; then
      command -v open >/dev/null 2>&1 && open "$DASH"
      return
    fi
  done
}

echo "NB3 V2 bot - SIMULATED \$50,000 demo (no real money, no real orders)"
echo "-----------------------------------------------------------------"

# 1. dependencies
[[ -x "$PY" ]] || fail "not installed yet. Open Terminal in this folder and run:  bash install_mac.sh"
"$PY" -c "import requests, numpy, nb3bot" 2>/dev/null || fail "packages missing. Run again:  bash install_mac.sh"

# 2. demo configuration
if [[ ! -f nb3bot_demo.toml ]]; then
  "$PY" -m nb3bot init-config nb3bot_demo.toml --profile tradingview_50k_demo || fail "could not create nb3bot_demo.toml"
fi

# 3. safety: refuse anything that could send an order
echo
"$PY" -m nb3bot safety-check --config nb3bot_demo.toml \
  || fail "nb3bot_demo.toml could send real orders. The demo refuses to start. Delete nb3bot_demo.toml and run install_mac.sh."

# 4. market-data keys from the macOS Keychain (never stored in a file)
KEYID="$(security find-generic-password -a "$USER" -s nb3bot-alpaca-key-id -w 2>/dev/null || true)"
SECRET="$(security find-generic-password -a "$USER" -s nb3bot-alpaca-secret -w 2>/dev/null || true)"
if [[ -z "$KEYID" || -z "$SECRET" ]]; then
  echo
  echo "No Alpaca market-data keys in your Keychain, so the live demo cannot get QQQ prices."
  echo "  1) run the OFFLINE demo on SYNTHETIC prices (shows the whole bot and dashboard; no internet needed)"
  echo "  2) quit  (store keys with:  bash install_mac.sh )"
  read -r -p "Choice [1/2]: " choice
  if [[ "$choice" == "1" ]]; then
    open_when_up &
    "$PY" -m nb3bot demo --days 5 --wait
  fi
  pause
  exit 0
fi
export ALPACA_API_KEY_ID="$KEYID" ALPACA_API_SECRET_KEY="$SECRET"

# 5. read-only data check
echo
echo "Checking the market-data connection (read-only)..."
"$PY" -m nb3bot check --config nb3bot_demo.toml || fail "the data check failed (see above): check the keys and your internet."

# 6. start the bot; the dashboard opens in the browser when it is ready
echo
echo "Starting the bot. The dashboard will open at $DASH (first start: ~2 minutes of history download)."
echo "Leave this window open while it runs. Press Ctrl+C here to stop it."
open_when_up &
"$PY" -m nb3bot run --config nb3bot_demo.toml --mode paper
pause
