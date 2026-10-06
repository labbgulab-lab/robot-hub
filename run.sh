#!/usr/bin/env bash
# Robot Hub - one-command start (Linux/macOS).
#   ./run.sh            start the hub
#   ./run.sh --doctor   check the environment instead of starting
#
# The Reachy-Mini-Lite card needs Windows (USB PnP via WMI and the Reachy Mini
# Control app). It degrades to a disabled card with a message elsewhere.

set -euo pipefail
cd "$(dirname "$0")"

PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "Creating .venv ..."
  python3 -m venv .venv
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
