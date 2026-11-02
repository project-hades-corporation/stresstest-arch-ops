#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

echo "=== Architecture Stress Platform setup ==="

PYTHON_CMD=()
select_python() {
  local candidate=("$@")
  if command -v "${candidate[0]}" >/dev/null 2>&1 &&
    "${candidate[@]}" -c \
      'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
      >/dev/null 2>&1; then
    PYTHON_CMD=("${candidate[@]}")
    return 0
  fi
  return 1
}

select_python python3 || select_python python || select_python py -3 || {
  echo "ERROR: Python 3.10 or newer is required." >&2
  exit 1
}
echo "[OK] Using $("${PYTHON_CMD[@]}" --version 2>&1)."

if ! command -v node >/dev/null 2>&1 ||
  ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 18 ? 0 : 1)'; then
  echo "ERROR: Node.js 18 or newer is required." >&2
  exit 1
fi
command -v npm >/dev/null 2>&1 || {
  echo "ERROR: npm is required. Install Node.js 18 or newer, then retry." >&2
  exit 1
}
echo "[OK] Node.js $(node --version)."

VENV_PYTHON="$APP_DIR/.venv/Scripts/python.exe"
if [ ! -x "$VENV_PYTHON" ]; then
  echo "Creating Python virtual environment..."
  "${PYTHON_CMD[@]}" -m venv "$APP_DIR/.venv"
else
  if ! "$VENV_PYTHON" -c \
    'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "ERROR: The existing .venv does not use Python 3.10 or newer." >&2
    echo "Rename or remove .venv, then run setup.sh again." >&2
    exit 1
  fi
  echo "Reusing existing Python virtual environment."
fi

echo "Installing Python dependencies..."
"$VENV_PYTHON" -m pip install -r "$APP_DIR/requirements.txt"

echo "Installing frontend dependencies..."
(
  cd "$APP_DIR/frontend"
  npm install
)

echo
echo "Setup complete! Open this workspace in your IDE, open your agent chat / Copilot tab, and type: 'Run the stress-arch skill to analyze my architecture.'"
