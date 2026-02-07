# Datang Reader - RFID Attendance System

Split-architecture RFID attendance tracking for Datang API with Docker deployment and offline queue support.

## Architecture

```
┌─────────────────┐
│  RFID Reader    │  (USB HID Keyboard)
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  GUI Client     │  client/gui/
│  (Host)         │  PyQt5 Interface
└────────┬────────┘
         │ HTTP POST :8080
         ↓
┌─────────────────┐
│  Docker Server  │  server/
│  - HTTP API     │  Flask HTTP Server
│  - Auth Manager │
│  - Offline Queue│
└─────────────────┘
```

**Why split?**
- **Docker Server**: Easy deployment, updates, isolation
- **Host GUI**: Direct USB RFID reader access
- Best of both worlds!

---

## Quick Start

### 1. Deploy Docker Server

```bash
cd server/
cp .env.example .env
nano .env  # Configure credentials

./deploy.sh
```

**Deployed:**
- HTTP server on port 8080
- Persistent data in `docker-data/`
- Offline queue with auto-sync

### 2. Setup GUI Client

```bash
cd client/
cp .env.example .env
nano .env  # Configure GUI settings (optional)

./install.sh  # Creates venv automatically
./run-gui.sh
```

### 3. Test the System

```bash
# Check server health
curl http://localhost:8080/health

# Test card submission
curl -X POST http://localhost:8080/card \
  -H "Content-Type: application/json" \
  -d '{"card_id": "1234567890"}'
```

---

## Configuration

### Environment Variables (.env)

Each component has its own `.env` file:

**Server** (`server/.env`):
```env
DATANG_API_BASE_URL=https://datang.my/api/reader/v1
DATANG_READER_USERNAME=your_username
DATANG_READER_PASSWORD=your_password
DATANG_DEVICE_ID=docker-reader-01
DATANG_MOCK_API=false
```

**Client** (`client/.env`):
```env
DATANG_FULLSCREEN=true   # GUI fullscreen mode
DATANG_ENABLE_PULSE=true # Breathing animation
```

**Security:**
- Never commit `.env` to git
- Each `.env` file lives next to its `.env.example`

### RFID Reader Setup

1. Plug in USB RFID reader (HID keyboard type)
2. No drivers needed - works as standard keyboard
3. Test: Open text editor, scan card (should type ID + Enter)
4. Start GUI client to capture scans

---

## Directory Structure

```
datang-reader/
├── docker-data/          # Persistent data (auto-created)
│   ├── token             # Authentication token
│   ├── queue.db          # Offline queue (BACKUP THIS!)
│   └── logs/             # Application logs
│
├── server/               # 🐳 DOCKER CONTAINER
│   ├── .env.example      # Server env template
│   ├── .env              # Server config (create from .env.example)
│   ├── deploy.sh         # Deploy Docker container
│   ├── Dockerfile        # Container image
│   ├── docker-compose.yml# Docker configuration
│   ├── requirements.txt  # Server dependencies (Flask, requests)
│   ├── datang_reader.py  # Server entry point
│   └── src/              # Server source code
│       ├── http_server.py      # Flask HTTP API
│       ├── service_manager.py  # Core orchestration
│       ├── api_client.py       # Datang API client
│       ├── auth_manager.py     # Authentication
│       ├── offline_queue.py    # SQLite queue
│       ├── rfid_reader.py      # Serial RFID support
│       └── config.py           # Server configuration
│
└── client/               # 💻 HOST CLIENTS
    ├── .env.example      # Client env template
    ├── .env              # Client config (create from .env.example)
    ├── install.sh        # Setup client venv
    ├── run-gui.sh        # Launch GUI (auto-loads .env)
    ├── run-console.sh    # Launch console (testing)
    ├── venv/             # Virtual environment (auto-created)
    │
    ├── gui/              # PyQt5 GUI Application
    │   ├── input_client_gui.py  # Main GUI app
    │   ├── config.py            # GUI configuration
    │   ├── requirements.txt     # PyQt5, requests, pystray
    │   └── assets/
    │       └── logo/            # SMKSAT logo
    │
    └── console/          # Console Client (Testing)
        └── input_client.py      # Simple console input
```

---

## Usage

### Server Management

```bash
cd server/

# View logs
docker compose logs -f

# Restart
docker compose restart

# Stop
docker compose down

# Manual queue sync
curl -X POST http://localhost:8080/sync

# Check status
curl http://localhost:8080/status
```

### GUI Client

```bash
cd client/

# Start GUI
./run-gui.sh

# Start console version (testing)
./run-console.sh

# Custom container URL
./run-gui.sh --url http://192.168.1.100:8080

# Or activate venv manually
source venv/bin/activate
cd gui && python3 input_client_gui.py
```

---

## Troubleshooting

### Server Issues

**Container won't start:**
```bash
cd server/
docker compose logs  # Check logs
cat .env             # Verify credentials
```

**Check server health:**
```bash
curl http://localhost:8080/health
```

### GUI Issues

**GUI can't connect:**
```bash
# Test server
curl http://localhost:8080/health

# Check container is running
cd server/ && docker compose ps
```

**PyQt5 installation fails on ARM:**
```bash
cd client/
rm -rf venv
./install.sh  # Answer 'y' to install system packages
```

**RFID reader not working:**
1. Test in text editor (should type card ID + Enter)
2. Ensure GUI window has focus
3. Check USB connection

### Debug Mode

```bash
# In server/.env
DATANG_LOG_LEVEL=DEBUG

# Restart server
cd server/ && docker compose restart

# View GUI logs
tail -f ~/.datang_reader.log
```

---

## Development

### Mock API Mode

Test without real API:

```bash
# In server/.env
DATANG_MOCK_API=true

# Restart server
cd server/ && docker compose restart
```

### Multiple Readers

```bash
# Edit server/docker-compose.yml to use different port
ports:
  - "8081:8080"

# Deploy
cd server/ && ./deploy.sh

# Connect GUI
cd client/ && ./run-gui.sh --url http://localhost:8081
```

---

## Security Notes

- Never commit `.env` or credentials to git
- Backup `docker-data/queue.db` regularly (contains attendance records)
- Restrict file permissions on token files
- Use firewall rules for port 8080 in production
- `.env` files should have 600 permissions (`chmod 600 server/.env client/.env`)

---

## Support

**Check logs:**
```bash
# Server
cd server/ && docker compose logs -f

# GUI Client
tail -f ~/.datang_reader.log
```

**Get help:**
1. Check logs first
2. Test with mock API: `DATANG_MOCK_API=true` in `server/.env`
3. Verify RFID reader works in text editor
4. Test server: `curl http://localhost:8080/health`

---

## License

Community-developed port of Datang Reader. Use in accordance with Datang's terms of service.
