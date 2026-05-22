#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Running within an existing desktop (X11/XFCE)
export QT_QPA_PLATFORM=xcb

# Set DISPLAY if not already set
if [ -z "$DISPLAY" ]; then
    export DISPLAY=:0
fi

# Change to GUI directory so relative paths work
cd "$SCRIPT_DIR/gui"

"$SCRIPT_DIR/venv/bin/python3" "$SCRIPT_DIR/gui/input_client_gui.py" "$@"
