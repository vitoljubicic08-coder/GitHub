#!/bin/bash
# NB3 V2 bot - macOS installer for the SIMULATED $50,000 demo (profile tradingview_50k_demo).
#
# Run it from the project folder:   bash install_mac.sh
#
# What it does (nothing outside this folder, never uses sudo, installs no system software):
#   1. finds Python 3.11 or newer (tells you how to get it if missing)
#   2. creates an isolated environment in .venv and installs the bot's Python packages into it
#   3. creates nb3bot_demo.toml from the tradingview_50k_demo profile and checks it cannot send orders
#   4. runs the self-tests
#   5. makes start_demo.command double-clickable
#   6. optionally stores your free Alpaca market-data keys in the macOS Keychain (not in any file)
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

if [[ "$(uname -s)" != "Darwin" && "${NB3_ALLOW_NON_MAC:-}" != "1" ]]; then
  die "this installer is for macOS (set NB3_ALLOW_NON_MAC=1 to try it elsewhere)"
fi

# 1. Python 3.11+
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$(command -v "$c")"
    break
  fi
done
if [[ -z "$PY" ]]; then
  die "Python 3.11 or newer is needed.
  Install it from https://www.python.org/downloads/macos/  (or, with Homebrew: brew install python@3.12)
  then run:  bash install_mac.sh"
fi
say "Using $PY ($("$PY" --version 2>&1))"

# 2. isolated environment
if [[ ! -x .venv/bin/python ]]; then
  say "Creating the isolated environment .venv"
  "$PY" -m venv .venv
fi
say "Installing the bot's Python packages into .venv"
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r nb3bot/requirements.txt

# 3. demo configuration
if [[ ! -f nb3bot_demo.toml ]]; then
  .venv/bin/python -m nb3bot init-config nb3bot_demo.toml --profile tradingview_50k_demo
else
  say "Keeping your existing nb3bot_demo.toml"
fi
say "Safety check of nb3bot_demo.toml"
.venv/bin/python -m nb3bot safety-check --config nb3bot_demo.toml \
  || die "nb3bot_demo.toml can send orders, the demo must not. Delete nb3bot_demo.toml and run this installer again."

# 4. self-tests
if [[ "${NB3_SKIP_TESTS:-}" != "1" ]]; then
  say "Running the self-tests (1-2 minutes; 2 tests that need the research data are skipped)"
  .venv/bin/python -m unittest discover -s nb3bot/tests -t . || die "self-tests failed: please send the output above"
fi

# 5. launcher
chmod +x start_demo.command install_mac.sh 2>/dev/null || true
if command -v xattr >/dev/null 2>&1; then          # files from a downloaded ZIP are quarantined by macOS
  xattr -d com.apple.quarantine start_demo.command install_mac.sh 2>/dev/null || true
fi

# 6. Alpaca keys -> macOS Keychain (only the launcher reads them, when it starts the bot)
store_keys() {
  say "Store your Alpaca market-data keys in the macOS Keychain"
  echo "Get them free: sign up at https://alpaca.markets , open the PAPER account, generate API keys."
  read -r -p "Alpaca API Key ID: " KEYID
  [[ -n "$KEYID" ]] || die "no key ID entered"
  security add-generic-password -U -a "$USER" -s nb3bot-alpaca-key-id -w "$KEYID"
  echo "Now paste the Alpaca SECRET key when macOS asks for 'password data' (typing stays hidden):"
  security add-generic-password -U -a "$USER" -s nb3bot-alpaca-secret -w
  echo "Keys stored in your login Keychain (items nb3bot-alpaca-key-id and nb3bot-alpaca-secret)."
}
if command -v security >/dev/null 2>&1 && [[ "${NB3_SKIP_KEYS:-}" != "1" ]]; then
  if security find-generic-password -a "$USER" -s nb3bot-alpaca-secret >/dev/null 2>&1; then
    read -r -p "Alpaca keys are already in your Keychain. Replace them? [y/N] " ans
    if [[ "$ans" =~ ^[Yy] ]]; then store_keys; fi
  else
    read -r -p "Store your Alpaca market-data keys now? (you can do it later by running this again) [Y/n] " ans
    if [[ ! "$ans" =~ ^[Nn] ]]; then store_keys; fi
  fi
fi

say "Installation finished."
echo "Start the demo:  double-click start_demo.command   (or in Terminal:  ./start_demo.command)"
echo "No Alpaca keys yet? start_demo.command offers the OFFLINE demo on synthetic prices."
