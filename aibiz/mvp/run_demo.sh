#!/usr/bin/env bash
# Start the Quotebook demo on this computer (macOS or Linux, Python 3.9+). Nothing is sent to anyone.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
CONFIG="${1:-config/demo_detailing.json}"     # or config/demo_cleaning.json
export QB_ADMIN_TOKEN="${QB_ADMIN_TOKEN:-$("$PY" -c 'import secrets; print(secrets.token_urlsafe(16))')}"
"$PY" -m quotebook --config "$CONFIG" init
"$PY" -m quotebook --config "$CONFIG" seed >/dev/null || true
echo
echo "Admin token for this run: $QB_ADMIN_TOKEN"
echo "Open http://127.0.0.1:8000/ (customer chat) and http://127.0.0.1:8000/admin (owner)"
echo
"$PY" -m quotebook --config "$CONFIG" --log-level WARNING serve --port "${PORT:-8000}"
