# Datang Reader Service

RFID attendance tracking system for Datang API with Docker deployment and offline queue support.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.8+ (for GUI input client on host)
- HID keyboard-emulating RFID reader

### 1. Docker Deployment (Recommended)

Deploy the main application in Docker:

```bash
# Configure credentials
cp .env.example .env
nano .env  # Edit with your credentials

# Deploy
./deploy-docker.sh
```

**What this does:**
- Creates isolated Docker container
- Sets up persistent data storage
- Exposes HTTP API on port 8080
- Handles authentication, queue, and sync

### 2. Setup GUI Input Client

Install dependencies and GUI client on host:

```bash
# One-command setup (creates venv automatically)
./install.sh

# Launch GUI
./run-gui.sh
```

**What the GUI does:**
- Captures RFID card scans from USB reader
- Sends to Docker container via HTTP
- Shows real-time status and statistics
- Provides manual testing interface

### 3. Test the System

```bash
# Check container health
curl http://localhost:8080/health

# Test with GUI
./run-gui.sh
# Type a 10-digit number in manual input field and press Submit

# Or test via curl
curl -X POST http://localhost:8080/card \
  -H "Content-Type: application/json" \
  -d '{"card_id": "1234567890"}'
```

---

## Architecture

```
┌─────────────────┐
│  RFID Reader    │ USB HID Keyboard
│  (Host)         │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  GUI Client     │ Python (venv)
│  (Host)         │ ./run-gui.sh
└────────┬────────┘
         │ HTTP POST
         ↓
┌─────────────────┐
│  Docker         │ Port 8080
│  Container      │
│  - API Client   │
│  - Auth Manager │
│  - Queue System │
└─────────────────┘
```

**Why this split architecture?**
- Docker container: Easy deployment, updates, isolation
- Host GUI client: Direct access to USB RFID reader
- Best of both worlds!

---

## Configuration

### Environment Variables (.env)

Create `.env` file with your credentials:

```env
DATANG_API_BASE_URL=https://datang.my/api/reader/v1
DATANG_READER_USERNAME=30370_reader78
DATANG_READER_PASSWORD=your_password_here
DATANG_DEVICE_ID=docker-reader-01
DATANG_MOCK_API=false
DATANG_FULLSCREEN=false  # Set to 'true' for GUI fullscreen mode
```

**Security:**
- Never commit `.env` to git
- Use environment variables, not hardcoded credentials
- Keep `.env` file permissions restricted

### RFID Reader Setup

1. **Plug in USB RFID reader** (HID keyboard type)
2. **No drivers needed** - works as standard keyboard
3. **Test it:** Open text editor and scan a card
   - Reader should type the card ID + Enter
4. **Start GUI client** to capture scans

---

## Usage

### Container Management

```bash
# View status
docker compose ps

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
# Start GUI
./run-gui.sh

# Start console version
./run-console.sh

# With custom container URL
./run-gui.sh --url http://192.168.1.100:8080

# Fullscreen mode (set DATANG_FULLSCREEN=true in .env, or:)
export DATANG_FULLSCREEN=true
./run-gui.sh

# Or activate venv manually
source venv/bin/activate
python3 input_client_gui.py
```

### Persistent Data

Data stored in `./docker-data/`:
- `token` - Authentication token
- `queue.db` - Offline attendance queue
- `logs/` - Application logs

**Important:** Backup `queue.db` regularly!

---

## Installation Options

### Option 1: Docker + GUI Client (Recommended)

```bash
./deploy-docker.sh  # Deploy container
./install.sh        # Setup GUI client
./run-gui.sh        # Start scanning
```

### Option 2: Native Installation (No Docker)

```bash
sudo ./install.sh --system  # System-wide installation
# Or
./install.sh --user        # User installation (no sudo)
```

For native installation:
- Creates systemd service (system mode)
- Or creates venv (user mode)
- Direct RFID reader access
- No container overhead

---

## Troubleshooting

### Docker Container Issues

**Container won't start:**
```bash
# Check logs
docker compose logs

# Verify .env file
cat .env

# Check port 8080 not in use
netstat -tulpn | grep 8080
```

**Container restarts continuously:**
```bash
# View recent logs
docker logs datang-reader --tail=50

# Common issues:
# - Missing/invalid credentials in .env
# - Python version mismatch
# - Port already in use
```

### GUI Client Issues

**PyQt5 not found / Build errors on Raspberry Pi:**
```bash
# Reinstall dependencies (uses requirements-gui.txt automatically)
rm -rf venv
./install.sh

# Note: If you see PyQt5 build errors with Docker, the issue is fixed
# in this version - Docker now uses requirements-docker.txt (no PyQt5)
```

**Can't connect to container:**
```bash
# Verify container is running
curl http://localhost:8080/health

# Check firewall
sudo ufw allow 8080
```

**RFID reader not working:**
1. Test in text editor first (should type card ID)
2. Check USB connection
3. Try different USB port
4. Verify reader is HID keyboard type

### Common Errors

**"externally-managed-environment" error:**
- Solution: Use `./install.sh` (creates venv automatically)
- Or: Create manual venv: `python3 -m venv venv && source venv/bin/activate`

**Permission denied (Docker):**
```bash
# Add user to docker group
sudo usermod -aG docker $USER
newgrp docker
```

**Token expired / Auth failed:**
```bash
# Re-login (in container)
docker exec -it datang-reader python datang_reader.py --login
```

### Health Checks

```bash
# Container health
curl http://localhost:8080/health

# Queue status
curl http://localhost:8080/status

# Test card submission
curl -X POST http://localhost:8080/card \
  -H "Content-Type: application/json" \
  -d '{"card_id": "1234567890"}'
```

---

## Advanced

### Custom Deployment

**Change container port:**
```yaml
# docker-compose.yml
ports:
  - "8081:8080"  # Use port 8081 instead
```

**Use different container URL:**
```bash
./run-gui.sh --url http://192.168.1.100:8081
```

**Run as systemd service:**
```bash
# Install GUI client as service
sudo cp systemd/input-client.service /etc/systemd/system/
sudo systemctl enable input-client
sudo systemctl start input-client
```

### Multiple Readers

Deploy multiple containers with different ports:
```bash
# Container 1
docker-compose -f docker-compose.yml -p reader1 up -d

# Container 2
docker-compose -f docker-compose-reader2.yml -p reader2 up -d

# GUI for reader 1
./run-gui.sh --url http://localhost:8080

# GUI for reader 2
./run-gui.sh --url http://localhost:8081
```

---

## Development

### Mock API Mode

Test without real API:
```bash
# Set in .env
DATANG_MOCK_API=true

# Or run with flag
python3 datang_reader.py --console --mock-api
```

### View Logs

```bash
# Container logs
docker compose logs -f

# GUI client logs
tail -f ~/.datang_reader.log

# Host system journal
journalctl -u input-client -f
```

---

## File Structure

```
datang-reader/
├── deploy-docker.sh          # Docker deployment script
├── install.sh                # Setup script (creates venv)
├── run-gui.sh                # GUI launcher
├── run-console.sh            # Console launcher
├── docker-compose.yml        # Docker configuration
├── Dockerfile                # Container image
├── .env.example              # Example environment variables
├── datang_reader.py          # Main application
├── input_client.py           # Console input client
├── input_client_gui.py       # GUI input client
├── requirements-docker.txt   # Docker container dependencies (Flask, requests)
├── requirements-gui.txt      # GUI client dependencies (PyQt5, requests)
├── requirements.txt          # (Deprecated - kept for compatibility)
├── src/                      # Source code
│   ├── config.py
│   ├── api_client.py
│   ├── auth_manager.py
│   ├── offline_queue.py
│   ├── http_server.py
│   └── gui_app.py
└── docker-data/              # Persistent data (auto-created)
    ├── token
    ├── queue.db
    └── logs/
```

### Python Dependencies

The project uses **separate requirements files** for different components:

- **`requirements-docker.txt`** - Used by Docker container (HTTP server only)
  - Flask (HTTP server)
  - requests (API client)
  - pytest (testing)

- **`requirements-gui.txt`** - Used by GUI client on host
  - PyQt5 (GUI framework)
  - requests (communicates with container)
  - pystray/Pillow (system tray support)

- **`requirements.txt`** - Deprecated (kept for backward compatibility)

**Why split?** The Docker container doesn't need PyQt5, and on ARM devices (like Raspberry Pi), PyQt5 compilation can fail. Splitting keeps builds faster and more reliable.

---

## Security Notes

- Never commit `.env` or credentials to git
- Keep `docker-data/` secure (contains queue database)
- Restrict file permissions on token files
- Use firewall rules for port 8080
- Backup `queue.db` regularly

---

## Support

**Check logs:**
```bash
docker compose logs -f          # Container
tail -f ~/.datang_reader.log    # GUI client
```

**Enable debug mode:**
```bash
# In .env
DATANG_LOG_LEVEL=DEBUG
docker compose restart
```

**Get help:**
1. Check logs first
2. Test with mock API: `DATANG_MOCK_API=true`
3. Verify RFID reader works in text editor
4. Check network connectivity: `curl https://datang.my`

---

## License

Community-developed port of Datang Reader. Use in accordance with Datang's terms of service.
