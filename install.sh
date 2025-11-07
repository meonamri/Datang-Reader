#!/bin/bash
#
# Datang Reader Linux Service - Installation Script
#
# This script installs the Datang Reader service on a Linux system.
# It must be run with sudo privileges.

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Installation paths
INSTALL_DIR="/opt/datang-reader"
SERVICE_USER="datang"
SERVICE_FILE="/etc/systemd/system/datang-reader.service"

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

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   print_msg "$RED" "Error: This script must be run as root (use sudo)"
   exit 1
fi

print_header "Datang Reader Linux Service - Installation"

# Detect distribution
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VER=$VERSION_ID
    print_msg "$GREEN" "Detected OS: $PRETTY_NAME"
else
    print_msg "$RED" "Error: Cannot detect Linux distribution"
    exit 1
fi

# Install dependencies
print_header "Installing Dependencies"

case $OS in
    ubuntu|debian)
        print_msg "$YELLOW" "Installing Python and dependencies..."
        apt-get update
        apt-get install -y python3 python3-pip python3-venv python3-pyqt5
        apt-get install -y git
        ;;
    fedora|rhel|centos)
        print_msg "$YELLOW" "Installing Python and dependencies..."
        dnf install -y python3 python3-pip python3-virtualenv python3-qt5
        dnf install -y git
        ;;
    arch)
        print_msg "$YELLOW" "Installing Python and dependencies..."
        pacman -Sy --noconfirm python python-pip python-pyqt5
        pacman -Sy --noconfirm git
        ;;
    *)
        print_msg "$YELLOW" "Warning: Unknown distribution. Attempting generic install..."
        ;;
esac

print_msg "$GREEN" "✓ Dependencies installed"

# Create service user
print_header "Creating Service User"

if id "$SERVICE_USER" &>/dev/null; then
    print_msg "$YELLOW" "User '$SERVICE_USER' already exists"
else
    useradd -r -s /bin/bash -d "$INSTALL_DIR" -m "$SERVICE_USER"
    print_msg "$GREEN" "✓ Created user '$SERVICE_USER'"
fi

# Add user to USB access groups
usermod -a -G dialout,plugdev "$SERVICE_USER" 2>/dev/null || true
print_msg "$GREEN" "✓ Added user to USB access groups"

# Create installation directory
print_header "Installing Service Files"

if [ -d "$INSTALL_DIR" ]; then
    print_msg "$YELLOW" "Backing up existing installation..."
    mv "$INSTALL_DIR" "${INSTALL_DIR}.backup.$(date +%Y%m%d_%H%M%S)" || true
fi

mkdir -p "$INSTALL_DIR"
print_msg "$GREEN" "✓ Created installation directory: $INSTALL_DIR"

# Copy files
print_msg "$YELLOW" "Copying service files..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cp -r "$SCRIPT_DIR/src" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/datang_reader.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"

# Make main script executable
chmod +x "$INSTALL_DIR/datang_reader.py"

print_msg "$GREEN" "✓ Service files installed"

# Create virtual environment
print_header "Creating Virtual Environment"

print_msg "$YELLOW" "Creating virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"
print_msg "$GREEN" "✓ Virtual environment created"

# Install Python dependencies
print_header "Installing Python Dependencies"

print_msg "$YELLOW" "Installing via pip in virtual environment..."
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

print_msg "$GREEN" "✓ Python dependencies installed"

# Set ownership
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# Install systemd service
print_header "Installing Systemd Service"

if [ -f "$SCRIPT_DIR/systemd/datang-reader.service" ]; then
    cp "$SCRIPT_DIR/systemd/datang-reader.service" "$SERVICE_FILE"

    # Reload systemd
    systemctl daemon-reload

    print_msg "$GREEN" "✓ Systemd service installed"
else
    print_msg "$YELLOW" "Warning: systemd service file not found"
fi

# Configuration
print_header "Configuration"

print_msg "$YELLOW" "IMPORTANT: Configure credentials via environment variables"
echo ""
echo "1. Edit the systemd service file to add credentials:"
echo "   sudo nano $SERVICE_FILE"
echo ""
echo "   Add these lines in the [Service] section:"
echo "   Environment=\"DATANG_READER_USERNAME=your_username_here\""
echo "   Environment=\"DATANG_READER_PASSWORD=your_password_here\""
echo ""
echo "   Then reload systemd: sudo systemctl daemon-reload"
echo ""
echo "2. For manual testing, export environment variables first:"
echo "   export DATANG_READER_USERNAME=\"your_username_here\""
echo "   export DATANG_READER_PASSWORD=\"your_password_here\""
echo ""
echo "3. Test RFID reader:"
echo "   sudo -u $SERVICE_USER $INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/datang_reader.py --test-reader"
echo ""
echo "4. Login and save authentication token:"
echo "   sudo -u $SERVICE_USER $INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/datang_reader.py --login"
echo ""
echo "SECURITY NOTE: Never hardcode credentials in config.py - use environment variables only!"
echo ""

# Installation complete
print_header "Installation Complete!"

echo "Service commands:"
echo "  Enable auto-start:  sudo systemctl enable datang-reader"
echo "  Start service:      sudo systemctl start datang-reader"
echo "  Stop service:       sudo systemctl stop datang-reader"
echo "  View status:        sudo systemctl status datang-reader"
echo "  View logs:          sudo journalctl -u datang-reader -f"
echo ""
echo "Manual testing:"
echo "  Console mode:  sudo -u $SERVICE_USER $INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/datang_reader.py --console"
echo "  GUI mode:      sudo -u $SERVICE_USER $INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/datang_reader.py --gui"
echo "  Show status:   sudo -u $SERVICE_USER $INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/datang_reader.py --status"
echo ""
print_msg "$GREEN" "Installation successful!"
echo ""
