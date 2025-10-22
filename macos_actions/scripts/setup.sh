#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${HOME}/ollama/macos_actions"
PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.11}"
ACTIONS_SUPPORT_DIR="${HOME}/Library/Application Support/macos_actions"
ACTIONS_FILE="${ACTIONS_SUPPORT_DIR}/actions.yml"

info() { printf "\033[1;34m[INFO]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[WARN]\033[0m %s\n" "$*"; }
error() { printf "\033[1;31m[ERR ]\033[0m %s\n" "$*"; }

if [[ ! -x "$PYTHON_BIN" ]]; then
  error "Python interpreter not found at $PYTHON_BIN"
  warn  "Install it with 'brew install python@3.11' or set PYTHON_BIN before running." 
  exit 1
fi

info "Using Python: $PYTHON_BIN"

if [[ ! -d "$PROJECT_DIR" ]]; then
  error "Project directory $PROJECT_DIR not found. Clone the repo to ~/ollama first."
  exit 1
fi

cd "$PROJECT_DIR"

info "Removing existing virtualenv (if any)"
rm -rf .venv

info "Creating virtualenv"
"$PYTHON_BIN" -m venv .venv
source .venv/bin/activate

info "Upgrading pip"
pip install --upgrade pip >/dev/null

info "Installing requirements"
pip install -r requirements.txt

info "Ensuring today_events.py is executable"
chmod +x scripts/today_events.py

mkdir -p "$ACTIONS_SUPPORT_DIR"
if [[ ! -f "$ACTIONS_FILE" ]]; then
  info "Copying default actions.yml to $ACTIONS_FILE"
  cp config/actions.example.yml "$ACTIONS_FILE"
else
  warn "Existing actions.yml found at $ACTIONS_FILE (left untouched)."
fi

if security find-generic-password -s osx_actions_key >/dev/null 2>&1; then
  info "Keychain secret 'osx_actions_key' already exists"
else
  warn "Keychain entry 'osx_actions_key' missing. Generating one now."
  RAND_KEY=$(openssl rand -base64 32)
  security add-generic-password -a "$USER" -s osx_actions_key -w "$RAND_KEY"
  info "Stored new key under 'osx_actions_key'"
fi

read -r -p "Run calendar authorization helper now? [Y/n] " reply
echo
if [[ "${reply:-Y}" =~ ^[Yy]$ ]]; then
  info "Running calendar authorization helper"
  python scripts/today_events.py || warn "today_events.py exited with non-zero status"
else
  warn "Skipping calendar authorization; remember to run scripts/today_events.py manually."
fi

deactivate

cat <<OUT

Setup complete.
To start the gateway:
  cd ~/ollama
  source macos_actions/.venv/bin/activate
  export OSX_ACTIONS_KEY="\$(security find-generic-password -s osx_actions_key -w)"
  export OSX_ACTIONS_CONFIG="\${HOME}/Library/Application Support/macos_actions/actions.yml"
  python -m uvicorn macos_actions.service.main:app --host 127.0.0.1 --port 8765 --app-dir .

OUT
