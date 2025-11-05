# Datang Reader Service

A cross-platform port of the Datang Reader Android attendance system. Works on Windows, Linux, and macOS with HID keyboard-emulating RFID readers.

> **📢 API Status**: ✅ **Integration Complete** (Nov 2, 2025)
> Real API endpoints have been captured and integrated. See `API_ENDPOINTS_CAPTURED.md` for details.
> **Current Phase**: Ready for hardware testing and deployment.

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

### Quick Install

Run the automated installation script:

```bash
sudo bash install.sh
```

This will:
- Install required system packages
- Create service user
- Copy service files to `/opt/datang-reader`
- Install Python dependencies
- Set up systemd service

### Manual Installation

1. **Install dependencies**:

```bash
# Ubuntu/Debian
sudo apt-get install python3 python3-pip python3-pyqt5

# Fedora/RHEL
sudo dnf install python3 python3-pip python3-qt5

# Arch
sudo pacman -S python python-pip python-pyqt5
```

2. **Install Python packages**:

```bash
pip3 install -r requirements.txt
```

3. **Plug in HID keyboard RFID reader**:
   - Simply connect via USB - no configuration needed
   - Reader will work like a keyboard automatically
   - Test by opening Notepad and scanning a card - the ID should appear

## Configuration

### Step 1: API Endpoints (✅ Already Done)

**Good news**: API endpoints have been captured and integrated! You don't need to do network interception.

The following are pre-configured in `src/config.py`:
- API Base URL: `https://datang.my/api/reader/v1`
- Login endpoint: `/login`
- Attendance endpoint: `/scan`
- API Version: `1`
- Authentication: Token in request body (body-based, not headers)

For technical details, see `API_ENDPOINTS_CAPTURED.md`.

### Step 2: Configure Your Credentials

Edit `src/config.py` and set your reader credentials:

```python
# Reader Credentials (REQUIRED - get from Datang Dashboard)
READER_USERNAME = "your_reader_username_here"  # Format: {org_id}_reader{number}
READER_PASSWORD = "your_reader_password_here"
```

Or set via environment variables:

```bash
export DATANG_READER_USERNAME="your_reader_username"
export DATANG_READER_PASSWORD="your_reader_password"
```

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

## Kiosk Setup

For a dedicated attendance kiosk:

1. **Auto-login**: Configure your display manager to auto-login

2. **Full-screen mode**: Set in `config.py`:
```python
FULLSCREEN = True
```

3. **Auto-start on boot**: Enable systemd service:
```bash
sudo systemctl enable datang-reader
```

4. **Disable screen sleep**:
```bash
# Add to ~/.xinitrc or desktop session startup
xset s off
xset -dpms
xset s noblank
```

5. **Hide cursor** (optional):
```bash
sudo apt-get install unclutter
unclutter -idle 0.1 &
```

## Troubleshooting

### RFID Reader Not Working

1. **Verify it's an HID keyboard reader**:
   - Open any text editor (Notepad, TextEdit, etc.)
   - Scan a card - it should type the card ID automatically
   - If nothing happens, your reader may not be HID keyboard type

2. **Focus issues in GUI mode**:
   - Make sure the GUI window is in focus
   - Don't click outside the input field while scanning
   - The GUI automatically refocuses every 2 seconds

3. **Console mode not reading**:
   - Make sure terminal window is active
   - Try typing a card ID manually to test
   - Check that Enter is being pressed after the card ID

### Authentication Failed

1. Verify credentials are correct (from Datang Dashboard)
2. Check API endpoint URL is correct
3. Test network connectivity:
```bash
curl https://datang.my/api/reader/v1/
```
4. Review captured API traffic to verify request format

### Cards Not Scanning

1. **Test reader in a text editor first**:
   - Open Notepad/TextEdit/any text editor
   - Scan a card
   - Verify card ID appears as text

2. **Check card format**: Must match reader frequency (125kHz)

3. **For GUI mode**: Ensure the window has focus
4. **For console mode**: Ensure terminal is active

5. **Review logs for errors**:
```bash
tail -f ~/.datang_reader.log
```

### Network/Sync Issues

1. Check internet connectivity
2. View offline queue:
```bash
python3 datang_reader.py --status
```
3. Manually trigger sync:
```bash
python3 datang_reader.py --sync
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

- Authentication tokens are stored in `~/.datang_reader_token` with restricted permissions (0600)
- Database file `~/.datang_reader_queue.db` contains attendance records
- Logs may contain card IDs - secure log file permissions
- Run service as dedicated user (not root) for security

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
- Check `NETWORK_INTERCEPTION_GUIDE.md` for API capture help
- Review logs: `~/.datang_reader.log`
- Test components individually before reporting issues

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
