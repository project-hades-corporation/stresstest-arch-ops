#!/usr/bin/env bash
# Start the Architecture Stress Platform without reinstalling dependencies.
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_LOG="${TMPDIR:-/tmp}/arch_stress_backend.log"
FRONTEND_LOG="${TMPDIR:-/tmp}/arch_stress_frontend.log"
PLATFORM="$(uname -s)"

case "$PLATFORM" in
  MINGW*|MSYS*|CYGWIN*)
    VENV_PYTHON="$APP_DIR/.venv/Scripts/python.exe"
    ;;
  *)
    VENV_PYTHON="$APP_DIR/.venv/bin/python"
    ;;
esac

echo "=== Architecture Stress Platform - start ==="

port_is_open() {
  "$VENV_PYTHON" -c \
    'import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)' \
    "$1" >/dev/null 2>&1
}

if [ ! -f "$VENV_PYTHON" ]; then
  echo "ERROR: Python environment not found. Run setup.sh once first."
  exit 1
fi
if [ ! -f "$APP_DIR/frontend/node_modules/next/dist/bin/next" ]; then
  echo "ERROR: Frontend dependencies not found. Run setup.sh once first."
  exit 1
fi
if ! "$VENV_PYTHON" -m uvicorn --version >/dev/null 2>&1; then
  echo "ERROR: Backend dependencies are missing. Run setup.sh once to install them."
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm is required to start the frontend."
  exit 1
fi

if "$VENV_PYTHON" -c \
  'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2)' \
  >/dev/null 2>&1; then
  echo "[OK] Backend is already running on :8000."
else
  if port_is_open 8000; then
    echo "ERROR: Port 8000 is occupied, but the backend health check failed."
    echo "Stop the process using port 8000, then run start.sh again."
    exit 1
  fi
  echo "Starting backend on :8000 ..."
  (
    cd "$APP_DIR"
    nohup "$VENV_PYTHON" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 \
      > "$BACKEND_LOG" 2>&1 < /dev/null &
    echo $! > "${TMPDIR:-/tmp}/arch_stress_backend.pid"
  )
fi

if "$VENV_PYTHON" -c \
  'import urllib.request; urllib.request.urlopen("http://127.0.0.1:3000", timeout=2)' \
  >/dev/null 2>&1; then
  echo "[OK] Frontend is already running on :3000."
else
  if port_is_open 3000; then
    echo "ERROR: Port 3000 is occupied, but the frontend health check failed."
    echo "Stop the process using port 3000, then run start.sh again."
    exit 1
  fi
  echo "Starting frontend on :3000 ..."
  (
    cd "$APP_DIR/frontend"
    nohup npm run dev -- --hostname 0.0.0.0 \
      > "$FRONTEND_LOG" 2>&1 < /dev/null &
    echo $! > "${TMPDIR:-/tmp}/arch_stress_frontend.pid"
  )
fi

echo "Waiting for services..."
BACKEND_READY=0
FRONTEND_READY=0
for _ in $(seq 1 30); do
  if [ "$BACKEND_READY" -ne 1 ] && "$VENV_PYTHON" -c \
    'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2)' \
    >/dev/null 2>&1; then
    BACKEND_READY=1
  fi
  if [ "$FRONTEND_READY" -ne 1 ] && "$VENV_PYTHON" -c \
    'import urllib.request; urllib.request.urlopen("http://127.0.0.1:3000", timeout=2)' \
    >/dev/null 2>&1; then
    FRONTEND_READY=1
  fi
  if [ "$BACKEND_READY" -eq 1 ] && [ "$FRONTEND_READY" -eq 1 ]; then
    break
  fi
  sleep 2
done

if [ "$BACKEND_READY" -ne 1 ]; then
  echo "ERROR: Backend did not become healthy. See $BACKEND_LOG"
  tail -n 30 "$BACKEND_LOG" 2>/dev/null || true
  exit 1
fi
if [ "$FRONTEND_READY" -ne 1 ]; then
  echo "ERROR: Frontend did not become available. See $FRONTEND_LOG"
  tail -n 30 "$FRONTEND_LOG" 2>/dev/null || true
  exit 1
fi

echo "[OK] Backend:  http://localhost:8000"
echo "[OK] Frontend: http://localhost:3000"
echo "Logs: $BACKEND_LOG and $FRONTEND_LOG"
