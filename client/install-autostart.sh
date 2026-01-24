#!/bin/bash
#
# Datang Reader GUI - Auto-start Installation Script
#
# This script installs the GUI client as a systemd user service
# that automatically starts when you log in to your desktop.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored message
print_msg() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Print section header
print_header() {
    echo ""
    echo "================================================================"
    print_msg "$BLUE" "$1"
    echo "================================================================"
    echo ""
}

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

print_header "Datang Reader GUI - Auto-start Installation"

# Check if running as root (should not be)
if [[ $EUID -eq 0 ]]; then
   print_msg "$RED" "Error: Do not run this script with sudo!"
   print_msg "$YELLOW" "This installs a user service that runs under your account."
   exit 1
fi

# Check if venv exists
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    print_msg "$RED" "Error: Virtual environment not found!"
    print_msg "$YELLOW" "Please run ./install.sh first to set up the GUI client."
    echo ""
    echo "Run: cd $SCRIPT_DIR && ./install.sh"
    exit 1
fi

# Check if run-gui.sh exists
if [ ! -f "$SCRIPT_DIR/run-gui.sh" ]; then
    print_msg "$RED" "Error: run-gui.sh not found!"
    print_msg "$YELLOW" "Please run ./install.sh first."
    exit 1
fi

# Create systemd user directory
print_header "Setting up Systemd User Service"

SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"
print_msg "$GREEN" "✓ Created systemd user directory: $SYSTEMD_USER_DIR"

# Copy service file
SERVICE_FILE="$PROJECT_ROOT/systemd/datang-reader-gui.service"
if [ ! -f "$SERVICE_FILE" ]; then
    print_msg "$RED" "Error: Service file not found: $SERVICE_FILE"
    exit 1
fi

# Update service file with current user and paths
print_msg "$YELLOW" "Configuring service file..."
sed "s|/home/user|$HOME|g" "$SERVICE_FILE" > "$SYSTEMD_USER_DIR/datang-reader-gui.service"
print_msg "$GREEN" "✓ Installed service file to $SYSTEMD_USER_DIR/datang-reader-gui.service"

# Reload systemd user daemon
print_header "Enabling Auto-start"

systemctl --user daemon-reload
print_msg "$GREEN" "✓ Reloaded systemd user daemon"

# Enable the service
systemctl --user enable datang-reader-gui.service
print_msg "$GREEN" "✓ Enabled auto-start on login"

# Enable lingering (optional - allows service to run even when not logged in)
echo ""
read -p "Enable service to run even when not logged in? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    loginctl enable-linger "$USER"
    print_msg "$GREEN" "✓ Enabled lingering for user $USER"
    print_msg "$YELLOW" "  Service will now run on boot, even without desktop login"
else
    print_msg "$YELLOW" "  Service will start only when you log in to desktop"
fi

# Installation complete
print_header "Installation Complete!"

echo "The GUI client will now auto-start when you log in."
echo ""
echo "Service management commands:"
echo ""
print_msg "$GREEN" "  Start now:       systemctl --user start datang-reader-gui"
print_msg "$GREEN" "  Stop service:    systemctl --user stop datang-reader-gui"
print_msg "$GREEN" "  Restart:         systemctl --user restart datang-reader-gui"
print_msg "$GREEN" "  View status:     systemctl --user status datang-reader-gui"
print_msg "$GREEN" "  View logs:       journalctl --user -u datang-reader-gui -f"
print_msg "$GREEN" "  Disable auto-start: systemctl --user disable datang-reader-gui"
echo ""

echo "Important notes:"
print_msg "$YELLOW" "  1. Make sure Docker server is running:"
echo "     cd $PROJECT_ROOT/server && docker compose up -d"
echo ""
print_msg "$YELLOW" "  2. The GUI will start automatically on next login"
echo ""
print_msg "$YELLOW" "  3. To start now without rebooting:"
echo "     systemctl --user start datang-reader-gui"
echo ""

# Ask if user wants to start now
read -p "Start the GUI service now? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Check if Docker server is running
    if ! docker ps | grep -q datang; then
        print_msg "$YELLOW" "Warning: Docker server doesn't appear to be running"
        echo ""
        read -p "Start Docker server first? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            cd "$PROJECT_ROOT/server"
            docker compose up -d
            print_msg "$GREEN" "✓ Started Docker server"
            sleep 3
        fi
    fi

    systemctl --user start datang-reader-gui
    print_msg "$GREEN" "✓ GUI service started"
    echo ""
    print_msg "$BLUE" "Check status with: systemctl --user status datang-reader-gui"
fi

echo ""
print_msg "$GREEN" "Setup complete! 🎉"
echo ""
