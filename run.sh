#!/bin/sh
# Start Intern Board at http://localhost:8765 (creates the virtualenv on first run).
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/uvicorn ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
PORT="${PORT:-8765}"
( sleep 1.5 && open "http://localhost:$PORT" ) >/dev/null 2>&1 &
exec .venv/bin/uvicorn board.main:app --host 127.0.0.1 --port "$PORT"
