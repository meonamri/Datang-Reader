#!/bin/bash
#
# Datang Reader Linux Service - Installation Script
#
# This script can install in two modes:
# 1. User mode (default) - Creates venv and sets up GUI client
# 2. System mode - Installs as systemd service (requires sudo)
#
# NOTE: For Docker deployment (recommended for production), use:
#   ./deploy-docker.sh
#

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

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# User mode installation (no sudo required)
install_user_mode() {
    print_header "Datang Reader - User Mode Installation"

    echo "This will set up the GUI Input Client in your local directory."
    echo "A virtual environment will be created with all dependencies."
    echo ""

    # Check Python version
    if ! command -v python3 &> /dev/null; then
        print_msg "$RED" "Error: python3 not found. Please install Python 3.8 or newer."
        exit 1
    fi

    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    print_msg "$GREEN" "✓ Found Python $PYTHON_VERSION"

    # Create virtual environment
    print_header "Creating Virtual Environment"

    VENV_DIR="$SCRIPT_DIR/venv"

    if [ -d "$VENV_DIR" ]; then
        print_msg "$YELLOW" "Virtual environment already exists at $VENV_DIR"
        read -p "Remove and recreate? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$VENV_DIR"
            print_msg "$GREEN" "✓ Removed old virtual environment"
        fi
    fi

    if [ ! -d "$VENV_DIR" ]; then
        print_msg "$YELLOW" "Creating virtual environment..."
        python3 -m venv "$VENV_DIR"
        print_msg "$GREEN" "✓ Virtual environment created at $VENV_DIR"
    fi

    # Install dependencies
    print_header "Installing Python Dependencies"

    print_msg "$YELLOW" "Upgrading pip..."
    "$VENV_DIR/bin/pip" install --upgrade pip -q

    print_msg "$YELLOW" "Installing dependencies from requirements-gui.txt..."
    "$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements-gui.txt" -q

    print_msg "$GREEN" "✓ All dependencies installed"

    # Make scripts executable
    chmod +x "$SCRIPT_DIR/input_client.py" 2>/dev/null || true
    chmod +x "$SCRIPT_DIR/input_client_gui.py" 2>/dev/null || true
    chmod +x "$SCRIPT_DIR/datang_reader.py" 2>/dev/null || true

    # Create wrapper scripts
    print_header "Creating Launcher Scripts"

    # GUI launcher
    cat > "$SCRIPT_DIR/run-gui.sh" << 'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/venv/bin/python3" "$SCRIPT_DIR/input_client_gui.py" "$@"
EOF
    chmod +x "$SCRIPT_DIR/run-gui.sh"
    print_msg "$GREEN" "✓ Created run-gui.sh"

    # Console launcher
    cat > "$SCRIPT_DIR/run-console.sh" << 'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/venv/bin/python3" "$SCRIPT_DIR/input_client.py" "$@"
EOF
    chmod +x "$SCRIPT_DIR/run-console.sh"
    print_msg "$GREEN" "✓ Created run-console.sh"

    # Installation complete
    print_header "Installation Complete!"

    echo "You can now run the input client in two ways:"
    echo ""
    echo "1. GUI Mode (recommended):"
    print_msg "$GREEN" "   ./run-gui.sh"
    echo ""
    echo "2. Console Mode:"
    print_msg "$GREEN" "   ./run-console.sh"
    echo ""
    echo "Advanced usage:"
    echo "  With custom container URL:"
    echo "    ./run-gui.sh --url http://192.168.1.100:8080"
    echo ""
    echo "  Or activate venv and run directly:"
    echo "    source venv/bin/activate"
    echo "    python3 input_client_gui.py"
    echo ""
    print_msg "$YELLOW" "Note: Make sure Docker container is running first!"
    echo "  Check with: docker compose ps"
    echo ""
}

# Check if running as root or regular user
if [[ $EUID -eq 0 ]]; then
    # Running as root - offer system mode
    INSTALL_MODE="system"
else
    # Running as regular user - default to user mode
    INSTALL_MODE="user"
fi

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --system)
            INSTALL_MODE="system"
            shift
            ;;
        --user)
            INSTALL_MODE="user"
            shift
            ;;
        --help)
            echo "Datang Reader Installation Script"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --user      User mode installation (creates venv, no sudo required)"
            echo "  --system    System mode installation (installs as systemd service, requires sudo)"
            echo "  --help      Show this help message"
            echo ""
            echo "If run without sudo: defaults to --user mode"
            echo "If run with sudo: prompts for mode selection"
            echo ""
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Run with --help for usage information"
            exit 1
            ;;
    esac
done

# Execute based on mode
if [[ "$INSTALL_MODE" == "user" ]]; then
    if [[ $EUID -eq 0 ]]; then
        print_msg "$YELLOW" "Warning: Running as root but --user mode selected."
        print_msg "$YELLOW" "User mode installation doesn't require sudo."
        echo ""
        read -p "Continue with user mode? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_msg "$YELLOW" "Installation cancelled."
            exit 0
        fi
    fi
    install_user_mode
    exit 0
fi

# System mode requires root
if [[ $EUID -ne 0 ]]; then
   print_msg "$RED" "Error: System mode installation requires sudo"
   print_msg "$YELLOW" "Run with: sudo ./install.sh --system"
   print_msg "$YELLOW" "Or run without sudo for user mode installation"
   exit 1
fi

print_header "Datang Reader Linux Service - System Mode Installation"

# Offer Docker deployment option
echo "This script will install Datang Reader natively using systemd."
echo ""
echo "Alternative: Docker deployment is recommended for production."
echo "  - Easier deployment and updates"
echo "  - Better isolation and resource management"
echo "  - Consistent across different Linux distributions"
echo ""
echo "To use Docker instead, run: ./deploy-docker.sh"
echo ""
read -p "Continue with native installation? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_msg "$YELLOW" "Installation cancelled."
    echo ""
    print_msg "$GREEN" "For Docker deployment, run: ./deploy-docker.sh"
    exit 0
fi
echo ""

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

cp -r "$SCRIPT_DIR/src" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/datang_reader.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/requirements-gui.txt" "$INSTALL_DIR/"

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
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements-gui.txt"

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
