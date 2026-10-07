#!/usr/bin/env bash
# One command to run Care Bot locally:  ./dev.sh
#   - starts the FastAPI backend (port 8000) and the Vite frontend (port 5173)
#   - reuses a server that is already running instead of failing
#   - Ctrl+C stops only the servers THIS script started
set -uo pipefail
cd "$(dirname "$0")"

API_PORT=8000
WEB_PORT=5173
LOGS=.dev-logs
mkdir -p "$LOGS"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
grey()  { printf '\033[90m%s\033[0m\n' "$*"; }
port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

# ---- sanity checks, with messages that say exactly what to do -------------------------------
[ -x .venv/bin/uvicorn ]        || { red "Python environment missing. Run: python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt"; exit 1; }
[ -f backend/.env ]             || { red "backend/.env is missing (database URLs and API key). See the README."; exit 1; }
[ -d frontend/node_modules ]    || { red "Frontend packages missing. Run: cd frontend && npm install"; exit 1; }

PIDS=()
cleanup() {
  echo; grey "Stopping the servers this script started…"
  for pid in "${PIDS[@]:-}"; do [ -n "$pid" ] && { pkill -P "$pid" 2>/dev/null; kill "$pid" 2>/dev/null; }; done
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

# ---- backend ---------------------------------------------------------------------------------
if port_busy $API_PORT; then
  if curl -fs -m 3 "http://127.0.0.1:$API_PORT/health" >/dev/null; then
    green "Backend already running on :$API_PORT (reusing it)"
  else
    red "Port $API_PORT is in use by something that is NOT Care Bot's API. Free it with: lsof -nP -iTCP:$API_PORT -sTCP:LISTEN"
    exit 1
  fi
else
  grey "Starting backend on :$API_PORT …  (log: $LOGS/backend.log)"
  ( cd backend && exec ../.venv/bin/uvicorn app.main:app --reload --port $API_PORT ) >"$LOGS/backend.log" 2>&1 &
  PIDS+=($!)
  for _ in $(seq 1 90); do
    curl -fs -m 2 "http://127.0.0.1:$API_PORT/health" >/dev/null && break
    kill -0 "${PIDS[0]}" 2>/dev/null || { red "Backend exited during startup. Last log lines:"; tail -15 "$LOGS/backend.log"; exit 1; }
    sleep 1
  done
  curl -fs -m 2 "http://127.0.0.1:$API_PORT/health" >/dev/null || { red "Backend did not become healthy in 90s. Last log lines:"; tail -15 "$LOGS/backend.log"; exit 1; }
  green "Backend is up:  http://127.0.0.1:$API_PORT/docs"
fi

# ---- frontend --------------------------------------------------------------------------------
if port_busy $WEB_PORT; then
  green "Frontend already running on :$WEB_PORT (reusing it)"
else
  grey "Starting frontend on :$WEB_PORT …  (log: $LOGS/frontend.log)"
  ( cd frontend && exec npm run dev ) >"$LOGS/frontend.log" 2>&1 &
  PIDS+=($!)
  for _ in $(seq 1 30); do port_busy $WEB_PORT && break; sleep 1; done
  port_busy $WEB_PORT || { red "Frontend did not start. Last log lines:"; tail -15 "$LOGS/frontend.log"; exit 1; }
fi

# ---- final end-to-end check through the proxy (the exact path the browser uses) ---------------
if curl -fs -m 5 "http://localhost:$WEB_PORT/api/health" >/dev/null; then
  green "Care Bot is ready  →  http://localhost:$WEB_PORT"
else
  red "The frontend cannot reach the backend through its /api proxy. Check $LOGS/frontend.log"
  exit 1
fi

if [ ${#PIDS[@]} -eq 0 ]; then
  grey "Nothing was started by this script (both servers were already running)."; exit 0
fi
grey "Press Ctrl+C to stop.  Logs: tail -f $LOGS/backend.log $LOGS/frontend.log"
wait
