#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load client environment variables if .env exists
# Use sed to strip carriage returns (handles CRLF line endings from Windows/editors)
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source <(sed 's/\r$//' "$SCRIPT_DIR/.env")
    set +a
fi

"$SCRIPT_DIR/venv/bin/python3" "$SCRIPT_DIR/console/input_client.py" "$@"
