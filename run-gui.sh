#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Running within an existing desktop (X11/XFCE)
# Use XCB platform plugin to run as a normal GUI app
export QT_QPA_PLATFORM=xcb

# Set DISPLAY if not already set
if [ -z "$DISPLAY" ]; then
    export DISPLAY=:0
fi

# For kiosk mode without desktop (exclusive display access):
# export QT_QPA_PLATFORM=eglfs  # Requires stopping X11/desktop first
# export QT_QPA_PLATFORM=linuxfb  # Alternative without GPU acceleration

"$SCRIPT_DIR/venv/bin/python3" "$SCRIPT_DIR/input_client_gui.py" "$@"
