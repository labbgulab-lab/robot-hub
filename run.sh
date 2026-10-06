#!/usr/bin/env bash
# Robot Hub - one-command start (macOS/Linux).
#   ./run.sh            start the hub
#   ./run.sh --doctor   check the environment instead of starting
#
# The Reachy-Mini-Lite card needs Windows (USB PnP via WMI and the Reachy Mini
# Control app). It degrades to a disabled card with a message elsewhere.

set -euo pipefail
cd "$(dirname "$0")"

PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  # The hub needs Python 3.11+. A Mac's own python3 is often 3.9, so take the
  # newest one installed (python.org or Homebrew) before falling back.
  BASE=""
  for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
      BASE="$c"; break
    fi
  done
  if [ -z "$BASE" ]; then
    echo "Python 3.11 or newer is needed: https://www.python.org/downloads/ (or: brew install python@3.12)"
    exit 1
  fi
  echo "Creating .venv with $BASE ..."
  "$BASE" -m venv .venv
  "$PY" -m pip install --upgrade pip --quiet
  "$PY" -m pip install -r requirements.txt
fi

if [ ! -f config.toml ]; then
  echo "No config.toml - using config.example.toml. Copy and edit it to set your paths."
fi

if [ "${1:-}" = "--doctor" ]; then
  exec "$PY" -m hub.doctor
fi

exec "$PY" -m hub.main
