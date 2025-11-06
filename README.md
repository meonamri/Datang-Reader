# Datang Reader Service

A cross-platform port of the Datang Reader Android attendance system. Works on Windows, Linux, and macOS with HID keyboard-emulating RFID readers.

## Features

- **HID Keyboard RFID Reader**: Reads 125kHz RFID cards via HID keyboard-emulating readers (no drivers needed)
- **Contactless Attendance**: Record attendance by simply scanning RFID cards (reader types card ID automatically)
- **Offline Queue**: Automatically queues attendance records when network is unavailable
- **Auto-Sync**: Syncs queued records when connection is restored
- **GUI Kiosk Mode**: Full-screen graphical interface for dedicated terminals
- **Console Mode**: Headless operation for servers
- **Systemd Integration**: Auto-start on boot with systemd service
- **Token Authentication**: Secure authentication with persistent token storage

## Architecture

The system consists of several components:

- **RFID Reader Module**: Handles HID keyboard input from RFID readers
- **API Client**: Communicates with Datang attendance API
- **Authentication Manager**: Manages login tokens and re-authentication
- **Offline Queue**: SQLite-based queue for offline attendance records
- **GUI Application**: PyQt5-based kiosk interface
- **Service Manager**: Orchestrates all components

## Prerequisites

### Hardware

- **Computer**: Windows PC, Linux PC, or macOS machine (cross-platform)
- **RFID Reader**: USB HID keyboard-emulating 125kHz RFID reader (the cheap ones that act as keyboards)
- **Network**: WiFi or Ethernet connection
- **Display**: Optional for GUI mode

**Note**: HID keyboard readers work on Windows, Linux, and macOS without any drivers. They simply type the card ID when scanned.

### Software

- **Operating System**: Windows 10/11, Linux (Ubuntu, Debian, Fedora, etc.), or macOS
- **Python**: 3.8 or higher
- **PyQt5**: For GUI mode (optional for console-only)
- **No drivers needed**: HID keyboard readers work as standard keyboards

## Installation

### Prerequisites

Ensure you have Python 3.8 or higher installed:

```bash
# Check Python version
python --version  # or python3 --version
```

### Windows Installation

1. **Install Python** (if not already installed):
   - Download Python 3.8+ from [python.org](https://www.python.org/downloads/)
   - During installation, check "Add Python to PATH"
   - Verify installation: `python --version`

2. **Install dependencies**:

```cmd
# Navigate to project directory
cd C:\path\to\Datang-Reader

# Install Python packages
pip install -r requirements.txt
```

3. **Configure credentials** (REQUIRED):
   - Set environment variables with your reader credentials
   - See Configuration section for detailed instructions
   - Credentials are NOT stored in source code for security

4. **Connect RFID reader**:
   - Plug in USB HID keyboard RFID reader
   - No drivers needed - Windows recognizes it as a keyboard
   - Test by opening Notepad and scanning a card

### macOS Installation

1. **Install Python** (if not already installed):

```bash
# Using Homebrew (recommended)
brew install python@3.11

# Or download from python.org
# Verify installation
python3 --version
```

2. **Install dependencies**:

```bash
# Navigate to project directory
cd ~/path/to/Datang-Reader

# Install Python packages
pip3 install -r requirements.txt
```

3. **Configure credentials** (REQUIRED):
   - Set environment variables with your reader credentials
   - See Configuration section for detailed instructions
   - Credentials are NOT stored in source code for security

4. **Connect RFID reader**:
   - Plug in USB HID keyboard RFID reader
   - macOS recognizes it automatically
   - Test in TextEdit by scanning a card

### Linux Installation (Ubuntu/Debian)

#### Quick Install (Automated)

```bash
sudo bash install.sh
```

This will:
- Install required system packages
- Create service user
- Copy service files to `/opt/datang-reader`
- Install Python dependencies
- Set up systemd service

#### Manual Installation

1. **Install dependencies**:

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install python3 python3-pip python3-pyqt5

# Fedora/RHEL
sudo dnf install python3 python3-pip python3-qt5

# Arch Linux
sudo pacman -S python python-pip python-pyqt5
```

2. **Install Python packages**:

```bash
pip3 install -r requirements.txt
```

3. **Configure credentials** (REQUIRED):
   - Set environment variables with your reader credentials
   - See Configuration section for detailed instructions
   - Credentials are NOT stored in source code for security

4. **Connect RFID reader**:
   - Plug in USB HID keyboard RFID reader
   - No drivers needed - Linux recognizes it automatically
   - Test by opening a text editor and scanning a card

## Configuration

### Step 1: API Endpoints

The following are pre-configured in `src/config.py`:
- API Base URL: `https://datang.my/api/reader/v1`
- Login endpoint: `/login`
- Attendance endpoint: `/scan`
- API Version: `1`
- Authentication: Token in request body (body-based, not headers)

### Step 2: Configure Your Credentials (REQUIRED)

**IMPORTANT SECURITY NOTICE**: For security reasons, credentials MUST be set via environment variables. They are NOT stored in source code.

Get your reader credentials from the Datang Dashboard, then set environment variables:

**Linux/macOS**:
```bash
# Set environment variables (add to ~/.bashrc or ~/.zshrc for persistence)
export DATANG_READER_USERNAME="30370_reader78"  # Format: {org_id}_reader{number}
export DATANG_READER_PASSWORD="your_password_here"
```

**Windows (Command Prompt)**:
```cmd
# Set environment variables temporarily (current session only)
set DATANG_READER_USERNAME=30370_reader78
set DATANG_READER_PASSWORD=your_password_here
```

**Windows (PowerShell)**:
```powershell
# Set environment variables temporarily (current session only)
$env:DATANG_READER_USERNAME="30370_reader78"
$env:DATANG_READER_PASSWORD="your_password_here"
```

**Windows (Permanent - System Environment Variables)**:
```cmd
# Run as Administrator to set system-wide
setx DATANG_READER_USERNAME "30370_reader78"
setx DATANG_READER_PASSWORD "your_password_here"

# Or use GUI: Control Panel > System > Advanced > Environment Variables
```

**For systemd services** (add to service file):
```ini
[Service]
Environment="DATANG_READER_USERNAME=30370_reader78"
Environment="DATANG_READER_PASSWORD=your_password_here"
```

The application will fail to start with a clear error message if credentials are not set.

### Step 3: Hardware Setup

**HID Keyboard RFID Reader**:
- Plug in the USB RFID reader
- **No configuration needed** - works as a standard keyboard
- When you scan a card, the reader will type the card ID and press Enter automatically

**How it works**:
- **GUI mode**: Keeps an input field focused to capture card IDs
- **Console mode**: Uses Python's `input()` function to read card IDs
- **Cross-platform**: Works identically on Windows, Linux, and macOS

### Step 4: Test Components

1. **Check Status**:

```bash
python3 datang_reader.py --status
```

2. **Login**:

```bash
python3 datang_reader.py --login
```

3. **Test with HID Reader** (scan a card to test):

```bash
# GUI mode - scan cards in the GUI window
python3 datang_reader.py --gui --mock-api

# Console mode - scan cards in terminal (or type card ID manually for testing)
python3 datang_reader.py --console --mock-api
```

```bash
python3 datang_reader.py --console
```

## Usage

### Running the Service

**GUI Mode** (default):
```bash
python3 datang_reader.py --gui
```

**Console Mode** (no GUI):
```bash
python3 datang_reader.py --console
```

**Mock API Mode** (for development):
```bash
python3 datang_reader.py --gui --mock-api
```

### Commands

**Show Status**:
```bash
python3 datang_reader.py --status
```

**Login/Authentication**:
```bash
python3 datang_reader.py --login
```

**Sync Offline Queue**:
```bash
python3 datang_reader.py --sync
```

**Test RFID Reader**:
```bash
# Simply run console or GUI mode and scan a card
python3 datang_reader.py --console --mock-api
```

### Systemd Service

**Enable auto-start**:
```bash
sudo systemctl enable datang-reader
```

**Start service**:
```bash
sudo systemctl start datang-reader
```

**Stop service**:
```bash
sudo systemctl stop datang-reader
```

**View status**:
```bash
sudo systemctl status datang-reader
```

**View logs**:
```bash
sudo journalctl -u datang-reader -f
```

## Deployment

### Windows Deployment

#### Option 1: Run on Startup (User Login)

1. **Create a batch file** `start_datang_reader.bat`:

```batch
@echo off
cd C:\path\to\Datang-Reader
python datang_reader.py --gui
```

2. **Add to Startup folder**:
   - Press `Win + R`, type `shell:startup`, press Enter
   - Copy the batch file to the Startup folder
   - The service will start automatically when you log in

#### Option 2: Run as Windows Service

1. **Install NSSM** (Non-Sucking Service Manager):
   - Download from [nssm.cc](https://nssm.cc/download)
   - Extract `nssm.exe` to `C:\Windows\System32`

2. **Install service**:

```cmd
# Open Command Prompt as Administrator
nssm install DatangReader "C:\path\to\python.exe" "C:\path\to\Datang-Reader\datang_reader.py --console"

# Start service
nssm start DatangReader

# Service will now run on boot
```

3. **Manage service**:

```cmd
# Stop service
nssm stop DatangReader

# Remove service
nssm remove DatangReader confirm
```

#### Option 3: Task Scheduler (Recommended for Kiosk)

1. Open Task Scheduler (`taskschd.msc`)
2. Create Basic Task:
   - **Name**: Datang Reader
   - **Trigger**: At startup or At log on
   - **Action**: Start a program
   - **Program**: `C:\path\to\python.exe`
   - **Arguments**: `C:\path\to\Datang-Reader\datang_reader.py --gui`
   - **Start in**: `C:\path\to\Datang-Reader`
3. Check "Run with highest privileges"

### macOS Deployment

#### Option 1: Launch Agent (User Login)

1. **Create launch agent** `~/Library/LaunchAgents/com.datang.reader.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.datang.reader</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/path/to/Datang-Reader/datang_reader.py</string>
        <string>--gui</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/datang-reader.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/datang-reader-error.log</string>
    <key>WorkingDirectory</key>
    <string>/path/to/Datang-Reader</string>
</dict>
</plist>
```

2. **Load the agent**:

```bash
launchctl load ~/Library/LaunchAgents/com.datang.reader.plist
launchctl start com.datang.reader
```

3. **Manage the service**:

```bash
# Stop
launchctl stop com.datang.reader

# Unload
launchctl unload ~/Library/LaunchAgents/com.datang.reader.plist
```

#### Option 2: Login Items

1. Open **System Preferences** > **Users & Groups**
2. Select your user, go to **Login Items**
3. Click **+** and add a script that launches the reader
4. Create a simple shell script `start_datang.sh`:

```bash
#!/bin/bash
cd /path/to/Datang-Reader
/usr/local/bin/python3 datang_reader.py --gui
```

5. Make it executable: `chmod +x start_datang.sh`

### Linux Deployment

#### Option 1: Systemd Service (System-wide)

1. **Edit the systemd service file** `systemd/datang-reader.service`:

```ini
[Unit]
Description=Datang RFID Reader Service
After=network.target

[Service]
Type=simple
User=datang-reader
Group=datang-reader
WorkingDirectory=/opt/datang-reader
ExecStart=/usr/bin/python3 /opt/datang-reader/datang_reader.py --console
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

2. **Install and enable**:

```bash
# Copy service file
sudo cp systemd/datang-reader.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start
sudo systemctl enable datang-reader
sudo systemctl start datang-reader
```

3. **Manage service**:

```bash
# Check status
sudo systemctl status datang-reader

# View logs
sudo journalctl -u datang-reader -f

# Restart
sudo systemctl restart datang-reader

# Stop
sudo systemctl stop datang-reader
```

#### Option 2: User Systemd Service (No root required)

1. **Create user service** `~/.config/systemd/user/datang-reader.service`:

```ini
[Unit]
Description=Datang RFID Reader Service
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/Datang-Reader
ExecStart=/usr/bin/python3 %h/Datang-Reader/datang_reader.py --gui
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```

2. **Enable and start**:

```bash
# Reload user systemd
systemctl --user daemon-reload

# Enable and start
systemctl --user enable datang-reader
systemctl --user start datang-reader

# Enable lingering (service runs even when not logged in)
loginctl enable-linger $USER
```

#### Option 3: Desktop Autostart

1. **Create autostart entry** `~/.config/autostart/datang-reader.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=Datang Reader
Exec=/usr/bin/python3 /path/to/Datang-Reader/datang_reader.py --gui
Terminal=false
X-GNOME-Autostart-enabled=true
```

2. Make it executable:

```bash
chmod +x ~/.config/autostart/datang-reader.desktop
```

### Kiosk Mode Setup

For a dedicated attendance kiosk terminal:

#### All Platforms

1. **Enable full-screen mode** in `src/config.py`:

```python
FULLSCREEN = True
```

2. **Configure auto-login**:
   - **Windows**: Settings > Accounts > Sign-in options > Require sign-in (Never)
   - **macOS**: System Preferences > Users & Groups > Login Options > Automatic login
   - **Linux**: Configure your display manager (GDM, LightDM, etc.)

#### Linux-specific Kiosk Settings

3. **Disable screen sleep**:

```bash
# Add to ~/.xinitrc or startup script
xset s off
xset -dpms
xset s noblank
```

4. **Hide cursor** (optional):

```bash
sudo apt-get install unclutter
# Add to startup
unclutter -idle 0.1 &
```

5. **Disable Alt+F4 and other shortcuts** (GNOME):

```bash
gsettings set org.gnome.desktop.wm.keybindings close "[]"
```

## Troubleshooting

### Installation Issues

#### Windows

**Python not found:**
```cmd
# Verify Python installation
where python

# If not found, reinstall Python and check "Add Python to PATH"
```

**pip not found:**
```cmd
# Use python -m pip instead
python -m pip install -r requirements.txt
```

**PyQt5 installation fails:**
```cmd
# Try upgrading pip first
python -m pip install --upgrade pip

# Install PyQt5 separately
python -m pip install PyQt5
```

**Permission errors:**
- Run Command Prompt as Administrator
- Or install packages for current user only:
```cmd
pip install --user -r requirements.txt
```

#### macOS

**Python not found:**
```bash
# Install Homebrew first
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python
brew install python@3.11
```

**PyQt5 installation fails:**
```bash
# Install Qt dependencies first
brew install qt@5

# Then install PyQt5
pip3 install PyQt5
```

**"python3" command not found:**
```bash
# Add to ~/.zshrc or ~/.bash_profile
export PATH="/usr/local/opt/python@3.11/bin:$PATH"

# Reload shell
source ~/.zshrc
```

**Permission denied errors:**
```bash
# Don't use sudo with pip, use --user flag instead
pip3 install --user -r requirements.txt
```

#### Linux

**apt-get update fails:**
```bash
# Run with sudo
sudo apt-get update

# If repository issues, check /etc/apt/sources.list
```

**python3-pyqt5 not found (older distros):**
```bash
# Install via pip instead
pip3 install PyQt5
```

**systemd service fails to start:**
```bash
# Check service status
sudo systemctl status datang-reader

# Check logs
sudo journalctl -u datang-reader -n 50

# Common issues:
# 1. Incorrect Python path in service file
# 2. Missing permissions
# 3. Wrong working directory
```

### RFID Reader Issues

#### General (All Platforms)

**Reader not detected:**
1. Verify it's a USB HID keyboard-emulating reader
2. Try different USB port
3. Test in a text editor first (Notepad, TextEdit, etc.)
4. Scan a card - it should type the ID automatically

**Cards scan too slowly:**
- Some readers have adjustable beep/delay settings
- Check reader manual for configuration
- Card may need to be held closer/longer

**Card IDs appear garbled:**
1. Check keyboard layout settings (should be US English)
2. Reader may be in wrong output format
3. Try different reader if possible

#### Windows-specific

**Reader not working after system update:**
```cmd
# Unplug and replug the reader
# Check Device Manager for driver issues
devmgmt.msc

# Look under "Keyboards" - should appear as HID Keyboard Device
```

**GUI window doesn't capture scans:**
1. Disable any keyboard filter software
2. Check if antivirus is blocking input
3. Run as Administrator
4. Make sure no other application has keyboard focus

#### macOS-specific

**Reader requires permission:**
1. System Preferences > Security & Privacy > Privacy
2. Grant Input Monitoring permission to Terminal or Python
3. May need to restart application

**Keyboard input not captured:**
```bash
# Check if reader is recognized
system_profiler SPUSBDataType | grep -i keyboard
```

#### Linux-specific

**Permission denied accessing input device:**
```bash
# Add user to input group
sudo usermod -a -G input $USER

# Log out and log back in for changes to take effect
```

**Reader works in text editor but not in application:**
```bash
# Check if running in correct terminal/environment
# Make sure X11 or Wayland session is active
echo $DISPLAY
```

### Authentication Issues

**"READER_USERNAME is not set" or "READER_PASSWORD is not set" error:**
1. Credentials MUST be set via environment variables (not in config.py)
2. Set `DATANG_READER_USERNAME` and `DATANG_READER_PASSWORD` environment variables
3. See Configuration section for platform-specific instructions
4. For systemd services, add Environment= lines to service file
5. For Windows services, set system environment variables before starting

**Login fails with "Invalid credentials":**
1. Verify credentials are correct (get from Datang Dashboard)
2. Ensure no extra spaces in username/password
3. Check if reader account is active in Datang Dashboard
4. Credentials format: `{org_id}_reader{number}`
5. Verify environment variables are set: `echo $DATANG_READER_USERNAME` (Linux/macOS) or `echo %DATANG_READER_USERNAME%` (Windows)

**Token expired:**
```bash
# Re-authenticate
python datang_reader.py --login

# Token is stored in ~/.datang_reader_token
# If corrupted, delete and re-login
```

**Network timeout:**
1. Check internet connectivity:
```bash
# Windows
ping datang.my

# macOS/Linux
curl -I https://datang.my
```
2. Check firewall settings
3. Verify proxy settings if behind corporate firewall

**SSL certificate errors:**
```bash
# Update certificates
# Windows: Update Windows
# macOS: Update system
# Linux:
sudo apt-get install ca-certificates
sudo update-ca-certificates
```

### GUI Application Issues

#### Windows

**GUI doesn't start:**
1. Check if PyQt5 is installed: `pip list | findstr PyQt5`
2. Run in console mode to see errors: `python datang_reader.py --console`
3. Check for conflicting Qt installations

**Window appears off-screen:**
- Delete config file (if any) and restart
- Try windowed mode first, then switch to fullscreen

**Display scaling issues:**
1. Right-click python.exe > Properties > Compatibility
2. Check "Override high DPI scaling behavior"
3. Select "System" in dropdown

#### macOS

**GUI window unresponsive:**
```bash
# Make sure running in main thread
# May need to use pythonw instead of python3
# Install and use:
pythonw datang_reader.py --gui
```

**Application not showing in Dock:**
- This is normal for Python GUI apps
- Can create an .app bundle for proper integration

#### Linux

**No display / DISPLAY not set:**
```bash
# If running over SSH, enable X11 forwarding
ssh -X user@host

# Or set DISPLAY manually
export DISPLAY=:0
```

**GUI crashes on start:**
```bash
# Check Qt platform plugin
export QT_DEBUG_PLUGINS=1
python3 datang_reader.py --gui

# May need to install additional packages
sudo apt-get install libxcb-xinerama0
```

**Font rendering issues:**
```bash
# Install font configuration
sudo apt-get install fontconfig
fc-cache -fv
```

### Scanning/Attendance Issues

**Cards scan but not recorded:**
1. Check logs:
```bash
# Windows
type %USERPROFILE%\.datang_reader.log

# macOS/Linux
tail -f ~/.datang_reader.log
```
2. Verify API connection: `python datang_reader.py --status`
3. Check offline queue: `python datang_reader.py --status`

**Duplicate scans:**
- Service may be running multiple times
- Check for duplicate processes:
```bash
# Windows
tasklist | findstr python

# macOS/Linux
ps aux | grep datang_reader
```

**Offline queue not syncing:**
```bash
# Manually trigger sync
python datang_reader.py --sync

# Check queue database
# Windows: %USERPROFILE%\.datang_reader_queue.db
# macOS/Linux: ~/.datang_reader_queue.db
```

**API returns error:**
1. Check if card ID format is correct
2. Verify reader is assigned to correct organization
3. Check if card is registered in system
4. Review API response in logs

### Performance Issues

**High CPU usage:**
1. Check if multiple instances are running
2. Reduce polling frequency in config
3. Use console mode instead of GUI if not needed

**Memory leaks:**
1. Restart service periodically via systemd/Task Scheduler
2. Update to latest PyQt5: `pip install --upgrade PyQt5`

**Slow startup:**
1. Check network connectivity (API check on startup)
2. Clear old logs if very large
3. Optimize SQLite database:
```python
# In Python console
from src.offline_queue import AttendanceQueue
queue = AttendanceQueue()
queue.conn.execute("VACUUM")
```

### Deployment/Service Issues

#### Windows Service (NSSM)

**Service won't start:**
```cmd
# Check service status
nssm status DatangReader

# View service output
# Open Event Viewer > Windows Logs > Application
eventvwr.msc
```

**Service starts but doesn't work:**
1. Check working directory is set correctly
2. Verify Python path in service configuration
3. Check environment variables are accessible to service

#### macOS Launch Agent

**Launch agent won't load:**
```bash
# Check for syntax errors
plutil -lint ~/Library/LaunchAgents/com.datang.reader.plist

# View agent status
launchctl list | grep datang
```

**Agent loads but app doesn't run:**
```bash
# Check logs
tail -f /tmp/datang-reader-error.log

# Verify Python path
which python3
```

#### Linux Systemd

**Service fails to start:**
```bash
# Check detailed status
systemctl status datang-reader -l

# View recent logs
journalctl -u datang-reader -n 100

# Common issues:
# - User doesn't exist
# - Permissions on files
# - Incorrect paths in .service file
```

**Service starts but crashes:**
```bash
# Enable debug logging in config.py
# Then restart and check logs
sudo systemctl restart datang-reader
sudo journalctl -u datang-reader -f
```

### Database Issues

**Queue database corrupted:**
```bash
# Windows
del %USERPROFILE%\.datang_reader_queue.db

# macOS/Linux
rm ~/.datang_reader_queue.db

# Restart service - database will be recreated
```

**Unable to write to database:**
1. Check file permissions
2. Check disk space
3. Verify database location is writable

### Network Issues

**Intermittent connection:**
1. Check network stability
2. Increase retry attempts in config
3. Verify no proxy/firewall interference

**Works locally but not from remote site:**
1. Check if API is geolocked
2. Verify DNS resolution
3. Test with different network

### Getting Help

If issues persist:

1. **Collect logs:**
```bash
# Windows
type %USERPROFILE%\.datang_reader.log > debug_log.txt

# macOS/Linux
cat ~/.datang_reader.log > debug_log.txt
```

2. **Check system info:**
```bash
# Windows
systeminfo
python --version

# macOS/Linux
uname -a
python3 --version
lsusb  # For USB device info
```

3. **Test components individually:**
```bash
# Test authentication
python datang_reader.py --login

# Test status check
python datang_reader.py --status

# Test with mock API
python datang_reader.py --console --mock-api
```

4. **Enable debug mode** in `src/config.py`:
```python
DEBUG = True
LOG_LEVEL = "DEBUG"
```

## File Structure

```
datang-reader/
├── datang_reader.py          # Main entry point
├── requirements.txt          # Python dependencies (no pyserial needed)
├── install.sh                # Installation script (Linux only)
├── README.md                 # This file
├── src/                      # Source code
│   ├── __init__.py
│   ├── config.py             # Configuration
│   ├── rfid_reader.py        # HID keyboard RFID reader module
│   ├── api_client.py         # API client
│   ├── auth_manager.py       # Authentication manager
│   ├── offline_queue.py      # Offline queue system
│   ├── service_manager.py    # Service orchestrator
│   └── gui_app.py            # GUI application (with keyboard input capture)
└── systemd/                  # Systemd service files (Linux only)
    └── datang-reader.service
```

## Development

### Running with Mock API

For development without actual API access:

```bash
python3 datang_reader.py --gui --mock-api
```

This uses a mock API client that simulates responses.

### Testing

Test individual components:

```python
# Test RFID reader (HID keyboard mode)
from src.rfid_reader import RFIDReader
reader = RFIDReader()
reader.connect()  # Always succeeds for HID keyboards

# In your main loop, when card is scanned (keyboard input):
# reader.push_card_id(card_id)  # Push from keyboard input

# Then read it:
card_id = reader.read_card(timeout=1)
print(f"Card: {card_id}")

# Test API client
from src.api_client import DatangAPIClient
api = DatangAPIClient()
token = api.login()
api.submit_attendance(card_id="ABCD1234")

# Test offline queue
from src.offline_queue import AttendanceQueue
queue = AttendanceQueue()
queue.enqueue("ABCD1234", datetime.now())
stats = queue.sync_with_api(api)
```

## Security Notes

- **Credentials**: MUST be set via environment variables only - never hardcoded in source code
- **Authentication tokens**: Stored in `~/.datang_reader_token` with restricted permissions (0600 on Unix)
- **Database file**: `~/.datang_reader_queue.db` contains attendance records - secure file permissions
- **Logs**: May contain card IDs - ensure log file permissions are restricted
- **Service user**: Run service as dedicated user (not root/administrator) for security
- **Environment variables**: For production deployments, use secure methods to set credentials (systemd Environment, Windows service environment, etc.)
- **Git**: Never commit credentials to version control - they belong in environment variables only

## Contributing

To contribute:

1. Test with your RFID reader hardware
2. Report issues with detailed logs
3. Submit API endpoint documentation if you have it
4. Improve error handling and edge cases

## License

This is a community-developed port of the proprietary Datang Reader Android app.
Use responsibly and in accordance with Datang's terms of service.

## Support

For issues and questions:
- Review the comprehensive Troubleshooting section above
- Check logs: `~/.datang_reader.log` (Linux/macOS) or `%USERPROFILE%\.datang_reader.log` (Windows)
- Test components individually before reporting issues
- Enable debug mode in `src/config.py` for detailed logging

## Changelog

### Version 1.1.0 (2025-11-05)

- **HID keyboard RFID reader support** (replaces serial port readers)
- **Cross-platform compatibility** (Windows, Linux, macOS)
- Simplified hardware setup (no drivers needed)
- GUI with focused input field for card capture
- Console mode using Python's input() function
- Removed pyserial dependency

### Version 1.0.0 (2025-10-31)

- Initial release with serial port RFID readers
- Datang API integration (✅ complete)
- Offline queue with auto-sync
- PyQt5 GUI kiosk mode
- Console mode for headless operation
- Systemd service integration (Linux)
- Authentication token management
- Comprehensive error handling
