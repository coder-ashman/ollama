#!/bin/bash
set -euo pipefail
REPO_DIR="$HOME/ollama"
BASE_DIR="$REPO_DIR/macos_actions"

cd "$REPO_DIR"
source "$BASE_DIR/.venv/bin/activate"
export OSX_ACTIONS_CONFIG="$HOME/Library/Application Support/macos_actions/actions.yml"
export OSX_ACTIONS_KEY="$(/usr/bin/security find-generic-password -s osx_actions_key -w)"
exec python -m uvicorn macos_actions.service.main:app --host 127.0.0.1 --port 8765 --app-dir "$REPO_DIR"