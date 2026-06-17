# Datang Reader - RFID Attendance System

Split-architecture RFID attendance tracking for Datang API with Docker deployment, offline queue support, and automated IDME portal submission.

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
┌─────────────────┐       ┌──────────────────────┐
│  Docker Server  │  ←──  │  Tailscale Serve      │
│  - HTTP API     │       │  (optional)           │
│  - Auth Manager │       │  datang-reader.tailnet│
│  - Offline Queue│       │  HTTPS on your tailnet│
│  - IDME Module  │       └──────────────────────┘
└────────┬────────┘
         │ At each session cutoff (e.g. 12:00 / 16:00)
         ↓
┌─────────────────┐
│  IDME/MOEIS     │  Playwright (Firefox)
│  Portal         │  Auto-submit absences
└─────────────────┘
```

**Why split?**
- **Docker Server**: Easy deployment, updates, isolation
- **Host GUI**: Direct USB RFID reader access
- **IDME Module**: Auto-detects absent students and submits to MOEIS portal

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
- HTTP server on port 8080 (configurable via `DATANG_HOST_PORT` in `.env`)
- Persistent data in `docker-data/`
- Offline queue with auto-sync
- IDME module (disabled by default, enable via `IDME_ENABLED=true`)

### 2. Setup GUI Client

```bash
cd client/
cp .env.example .env
nano .env  # Configure GUI settings (optional)

./install.sh  # Creates venv automatically
./run-gui.sh
```

### 3. Enable Auto-start (Optional)

To have the GUI client start automatically on login:

```bash
cd client/
./install-autostart.sh
```

See [AUTOSTART.md](AUTOSTART.md) for full details and troubleshooting.

### 4. Test the System

```bash
# Check server health
curl http://localhost:8080/health

# Test card submission
curl -X POST http://localhost:8080/card \
  -H "Content-Type: application/json" \
  -d '{"card_id": "1234567890"}'
```

### 4. Expose via Tailscale (Optional)

If the server is running on a machine connected to [Tailscale](https://tailscale.com/), you can expose it as a named service accessible from anywhere on your tailnet over HTTPS:

```bash
cd server/
./tailscale-serve-setup.sh              # Defaults: port 8081, service name "datang-reader"
./tailscale-serve-setup.sh 8080         # Custom port
./tailscale-serve-setup.sh 8081 my-reader  # Custom port and service name
```

Once configured, the server is reachable at:
```
https://datang-reader.<your-tailnet>.ts.net
```

This uses `tailscale serve --service` to register a **named service** with its own DNS identity, separate from the machine's hostname. Useful when hosting multiple services on the same device.

```bash
# Test from any device on your tailnet
curl https://datang-reader.<your-tailnet>.ts.net/health

# Remove the service
./tailscale-serve-setup.sh --remove

# Check serve status
tailscale serve status
```

**Prerequisites:** Tailscale installed and logged in (`tailscale up`) on the host machine.

---

## Configuration

### Environment Variables (.env)

Each component has its own `.env` file:

**Server** (`server/.env`):
```env
# Datang API
DATANG_API_BASE_URL=https://datang.my/api/reader/v1
DATANG_READER_USERNAME=your_username
DATANG_READER_PASSWORD=your_password
DATANG_DEVICE_ID=docker-reader-01
DATANG_MOCK_API=false
DATANG_HOST_PORT=8080            # Host port (container always listens on 8080 internally)

# IDME Module (optional)
IDME_ENABLED=false               # Set true to enable IDME portal automation
IDME_CUTOFF_TIME_MORNING=12:00   # Upper forms (3-6) auto-submission time (24h)
IDME_CUTOFF_TIME_EVENING=16:00   # Lower forms (1-2) auto-submission time (24h)
IDME_ENCRYPTION_KEY=             # Fernet key for teacher password encryption
IDME_DEBUG=false                 # Save screenshots during automation
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
│   ├── logs/             # Application logs
│   └── idme/             # IDME data (database, screenshots)
│
├── server/               # 🐳 DOCKER CONTAINER
│   ├── .env.example      # Server env template
│   ├── .env              # Server config (create from .env.example)
│   ├── deploy.sh         # Deploy Docker container
│   ├── Dockerfile        # Container image (includes Playwright/Firefox)
│   ├── docker-compose.yml# Docker configuration
│   ├── tailscale-serve-setup.sh  # Expose as Tailscale service
│   ├── requirements.txt  # Server dependencies
│   ├── datang_reader.py  # Server entry point
│   └── src/              # Server source code
│       ├── http_server.py      # Flask HTTP API
│       ├── service_manager.py  # Core orchestration
│       ├── api_client.py       # Datang API client
│       ├── auth_manager.py     # Authentication
│       ├── offline_queue.py    # SQLite queue
│       ├── rfid_reader.py      # Serial RFID support
│       ├── gui_app.py          # PyQt5 kiosk GUI (optional)
│       ├── config.py           # Server configuration
│       └── idme/               # IDME portal automation module
│           ├── schema.sql           # IDME database schema
│           ├── idme_config.py       # Module configuration
│           ├── moeis_codes.py       # 97 MOEIS absence reason codes
│           ├── credential_manager.py# Fernet password encryption
│           ├── teacher_manager.py   # Teacher CRUD (Web UI backed)
│           ├── roster_manager.py    # Student roster (Excel import)
│           ├── scan_tracker.py      # Daily RFID scan tracking
│           ├── absence_detector.py  # Roster - scans = absent
│           ├── session_cache.py     # IDME session/CSRF caching
│           ├── login_engine.py      # 6-step IDME login (Playwright)
│           ├── form_filler.py       # MOEIS form automation
│           ├── orchestrator.py      # Main submission workflow
│           ├── scheduler.py         # Daily cutoff timer
│           ├── api_routes.py        # Flask blueprint (/idme/*)
│           └── templates/
│               └── settings.html    # Teacher management Web UI
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

# List failed scan records (card IDs, timestamps, error messages)
curl http://localhost:8080/failed
```

### GUI Client

```bash
cd client/

# Start GUI
./run-gui.sh

# Start console version (testing)
./run-console.sh

# Show failed scan records (card IDs, timestamps, error messages)
./run-console.sh --failed

# Custom container URL
./run-gui.sh --url http://192.168.1.100:8080

# Or activate venv manually
source venv/bin/activate
cd gui && python3 input_client_gui.py
```

---

## IDME Module (Automated MOEIS Submission)

The IDME module automates absence submission to Malaysia's IDME/MOEIS portal. It detects which students didn't scan their RFID card by a cutoff time and submits them as absent. The school runs two sessions — upper forms (3-6) in the morning and lower forms (1-2) in the afternoon — each with its own cutoff; a class is routed to a session by the leading form number in its class string.

### How It Works

```
RFID Scan → Datang API (unchanged)
               │
               └──→ scan_tracker records scan locally

...at each session cutoff (default 12:00 upper / 16:00 lower)...

Scheduler triggers → absence_detector: roster - scans = absent students
                   → login_engine: 6-step IDME login (Playwright/Firefox)
                   → form_filler: uncheck absent students, set reason code
                   → submit to MOEIS portal
```

All absences default to reason code `N0040027` (PONTENG - MALAS KE SEKOLAH). The module supports all 97 MOEIS reason codes for future expansion.

### Setup

**1. Enable the module** in `server/.env`:
```env
IDME_ENABLED=true
IDME_CUTOFF_TIME_MORNING=12:00   # upper forms (3-6)
IDME_CUTOFF_TIME_EVENING=16:00   # lower forms (1-2)
IDME_ENCRYPTION_KEY=your_fernet_key_here
```

Generate the encryption key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**2. Rebuild the Docker container** (first time only — installs Playwright/Firefox):
```bash
cd server/
./deploy.sh
```

**3. Add teachers** via Web UI at `http://localhost:8080/idme/settings`

Each teacher needs: name, IC number (12 digits), IDME password, and class name. Passwords are encrypted with Fernet before storage.

**4. Import student roster** via API:
```bash
curl -X POST http://localhost:8080/idme/roster/import \
  -H "Content-Type: application/json" \
  -d '{"excel_path": "/path/to/students.xlsx"}'
```

### API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/idme/status` | Module status and scan counts |
| GET | `/idme/settings` | Teacher management Web UI |
| POST | `/idme/teachers` | Add a teacher |
| PUT | `/idme/teachers/<id>` | Update a teacher |
| DELETE | `/idme/teachers/<id>` | Delete a teacher |
| POST | `/idme/teachers/<id>/test` | Test IDME login credentials |
| GET | `/idme/scans` | Today's scans (filter by `?class=5 UKM`) |
| POST | `/idme/submit` | Manual submission trigger |
| GET | `/idme/roster` | Student roster summary |
| POST | `/idme/roster/import` | Import roster from Excel |
| GET | `/idme/submissions` | Submission history |

### Manual Submission

Trigger IDME submission without waiting for the cutoff time:

```bash
# Submit for a specific class
curl -X POST http://localhost:8080/idme/submit \
  -H "Content-Type: application/json" \
  -d '{"class_name": "5 UKM"}'

# Submit all configured classes
curl -X POST http://localhost:8080/idme/submit \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Disabling

Set `IDME_ENABLED=false` in `server/.env` and restart. The Datang reader continues working normally without the IDME module.

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

### Failed Scans

**Identify which card IDs failed:**
```bash
# Via console client
cd client/ && ./run-console.sh --failed

# Via HTTP endpoint
curl http://localhost:8080/failed

# Directly in the SQLite database
sqlite3 -column -header ~/.datang_reader_queue.db \
  "SELECT id, card_id, timestamp, retry_count, last_error FROM attendance_queue WHERE status='failed';"
```

A scan is permanently marked `failed` after 5 retry attempts. The `last_error` column shows why it failed (e.g. token expired, attendance submission error). To retry failed scans, resolve the underlying issue and then trigger a manual sync:
```bash
curl -X POST http://localhost:8080/sync
```

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

**Multiple clients, one server** (same credentials/device ID):

Multiple GUI clients on separate machines can connect to a single server.
Each machine needs its own RFID reader (one reader per machine — HID keyboard
input goes to the focused window).

```bash
# Machine A
cd client/ && ./run-gui.sh --url http://192.168.1.100:8080

# Machine B
cd client/ && ./run-gui.sh --url http://192.168.1.100:8080
```

All scans are processed under the same `DATANG_READER_USERNAME` and `DATANG_DEVICE_ID`
configured in that server's `.env`.

**Multiple servers** (separate credentials/device IDs):

Each server needs its own Docker instance with unique container name, port,
credentials, and data directory. Edit `server/docker-compose.yml`:

```yaml
services:
  datang-reader-01:                        # Unique service name
    container_name: datang-reader-01       # Unique container name
    ports:
      - "8080:8080"                        # Unique host port
    volumes:
      - ../docker-data-01/token:/root/.datang_reader_token
      - ../docker-data-01/queue.db:/root/.datang_reader_queue.db
      - ../docker-data-01/logs:/data/logs
    # ... rest of config

  datang-reader-02:
    container_name: datang-reader-02
    ports:
      - "8081:8080"
    volumes:
      - ../docker-data-02/token:/root/.datang_reader_token
      - ../docker-data-02/queue.db:/root/.datang_reader_queue.db
      - ../docker-data-02/logs:/data/logs
    environment:
      - DATANG_READER_USERNAME=30370_reader79  # Different credentials
      - DATANG_READER_PASSWORD=other_password
      - DATANG_DEVICE_ID=docker-reader-02
      # ... rest of env vars from .env
```

Then connect each client to its server:

```bash
cd client/ && ./run-gui.sh --url http://localhost:8080  # Reader 01
cd client/ && ./run-gui.sh --url http://localhost:8081  # Reader 02
```

---

## Security Notes

- Never commit `.env` or credentials to git
- Backup `docker-data/queue.db` regularly (contains attendance records)
- Restrict file permissions on token files
- Use firewall rules for port 8080 in production, or use Tailscale Serve to avoid exposing the port publicly
- `.env` files should have 600 permissions (`chmod 600 server/.env client/.env`)
- IDME teacher passwords are encrypted with Fernet (AES-128-CBC) before database storage
- The `IDME_ENCRYPTION_KEY` should be generated once and never changed — changing it invalidates all stored passwords
- IDME session cookies are cached for 6 hours to reduce login frequency

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
