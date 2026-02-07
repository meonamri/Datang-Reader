#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load client environment variables if .env exists
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

"$SCRIPT_DIR/venv/bin/python3" "$SCRIPT_DIR/console/input_client.py" "$@"
