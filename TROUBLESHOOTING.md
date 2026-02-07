# Troubleshooting Guide

## Installation Issues

### PyQt5 Installation Hangs/Freezes on ARM Devices (Orange Pi, Raspberry Pi, etc.)

**Symptoms:**
- Installation appears stuck at "Installing dependencies from requirements-gui.txt"
- No output or progress indicators
- High CPU usage or system becomes unresponsive
- Takes 30+ minutes with no visible progress

**Cause:** PyQt5 is compiling from source on ARM architecture, which:
- Takes 30-60+ minutes on low-power devices
- Requires significant RAM (1GB barely sufficient, may use swap)
- The old `-q` (quiet) flag hid all compilation output

**Solution (Recommended - Use System PyQt5):**

1. **Cancel the stuck installation:** Press `Ctrl+C`

2. **Remove the partial venv:**
   ```bash
   rm -rf venv
   ```

3. **Run the updated install.sh:** (automatically uses system PyQt5)
   ```bash
   ./install.sh
   # When prompted, answer 'y' to install system packages
   ```

The updated script (as of 2025-11-21):
- ✓ Detects ARM/low-memory devices
- ✓ Recommends system PyQt5 packages (pre-compiled, instant)
- ✓ Creates venv with `--system-site-packages`
- ✓ Skips pip compilation of PyQt5
- ✓ Shows visible progress (no more silent hanging)

**Manual Installation (if needed):**
```bash
# Install system packages
sudo apt-get update
sudo apt-get install -y python3-pyqt5 qtbase5-dev python3-dev

# Remove old venv
rm -rf venv

# Re-run installation
./install.sh
```

---

### PyQt5 Build Errors

**Error:**
```
error: metadata-generation-failed
× Encountered error while generating package metadata.
╰─> PyQt5
```

**Cause:** Missing Qt5 development libraries.

**Solution:**

The updated `install.sh` automatically handles this, but if needed manually:
```bash
sudo apt-get update
sudo apt-get install -y python3-pyqt5 qtbase5-dev python3-dev
./install.sh
```

---

## Docker Issues

### Container Health Check Failing

**Symptoms:** GUI shows "Container Offline" status

**Troubleshooting steps:**

1. Check if container is running:
   ```bash
   docker compose ps
   ```

2. Check container logs:
   ```bash
   docker compose logs -f
   ```

3. Test health endpoint:
   ```bash
   curl http://localhost:8080/health
   ```

4. Restart container:
   ```bash
   docker compose restart
   ```

---

### Port Already in Use

**Error:** `Bind for 0.0.0.0:8080 failed: port is already allocated`

**Solution:**

1. Check what's using port 8080:
   ```bash
   sudo lsof -i :8080
   ```

2. Either:
   - Stop the conflicting service
   - Or change port in `docker-compose.yml`:
     ```yaml
     ports:
       - "8081:8080"  # Change host port to 8081
     ```
   - Then update GUI client:
     ```bash
     ./run-gui.sh --url http://localhost:8081
     ```

---

## Network Issues

### Cards Queuing Instead of Submitting

**Symptoms:** All cards show "Offline" icon (orange), queue size increasing

**Troubleshooting:**

1. Check network connectivity:
   ```bash
   curl -I https://datang.my
   ```

2. Check API base URL in `server/.env`:
   ```bash
   cat server/.env | grep DATANG_API_BASE_URL
   ```
   Should be: `https://datang.my/api` (or your custom endpoint)

3. Check container network:
   ```bash
   docker compose exec datang-reader curl -I https://datang.my
   ```

4. Test with mock API:
   ```bash
   # Edit server/.env
   echo "DATANG_MOCK_API=true" >> server/.env
   docker compose restart
   ```

5. Check authentication:
   ```bash
   # Check if token exists
   ls -lh docker-data/token

   # Force re-authentication
   rm docker-data/token
   docker compose restart
   ```

---

### Authentication Failures

**Error:** `Authentication failed` or `Token expired`

**Solution:**

1. Delete stored token:
   ```bash
   rm docker-data/token
   ```

2. Restart container (will re-authenticate):
   ```bash
   docker compose restart
   ```

3. Check credentials in `server/.env`:
   ```bash
   cat server/.env | grep DATANG_
   ```

4. Verify credentials work:
   ```bash
   # Using mock API
   DATANG_MOCK_API=true ./run-console.sh
   ```

---

## RFID Reader Issues

### Reader Not Detected

**Symptoms:** GUI doesn't capture card scans

**Troubleshooting:**

1. Test if reader works as keyboard:
   ```bash
   # Open a text editor, scan a card
   # Should type the card ID + Enter
   ```

2. Check USB connection:
   ```bash
   lsusb  # Should show reader as keyboard
   dmesg | grep -i usb  # Check for connection messages
   ```

3. Test with console client:
   ```bash
   ./run-console.sh
   # Scan a card
   ```

4. Ensure GUI window has focus (reader types into focused window)

---

### Serial RFID Reader (Alternative)

If using a serial-based RFID reader instead of HID keyboard:

1. Check device path:
   ```bash
   ls -l /dev/ttyUSB* /dev/ttyACM*
   ```

2. Add user to dialout group:
   ```bash
   sudo usermod -a -G dialout $USER
   # Log out and back in
   ```

3. Configure in code (modify `src/rfid_reader.py`)

---

## GUI Client Issues

### GUI Won't Start

**Error:** `ModuleNotFoundError: No module named 'PyQt5'`

**Solution:**

1. Ensure you ran `install.sh`:
   ```bash
   ./install.sh
   ```

2. Verify virtual environment exists:
   ```bash
   ls -ld venv/
   ```

3. Manually install dependencies:
   ```bash
   source venv/bin/activate
   pip install -r requirements-gui.txt
   ```

---

### GUI Shows Blank/Black Window

**Possible causes:**

1. Missing system Qt5 libraries:
   ```bash
   sudo apt-get install -y qtbase5-dev
   ```

2. Running over SSH without X forwarding:
   ```bash
   # Enable X forwarding
   ssh -X user@host
   ```

3. Display issues:
   ```bash
   export DISPLAY=:0
   ./run-gui.sh
   ```

---

## Offline Queue Issues

### Queue Not Syncing

**Symptoms:** Queue size stays high even when online

**Troubleshooting:**

1. Check queue database:
   ```bash
   sqlite3 docker-data/queue.db "SELECT COUNT(*) FROM queue WHERE status='pending';"
   ```

2. Manually trigger sync:
   ```bash
   curl -X POST http://localhost:8080/sync
   ```

3. Check sync logs:
   ```bash
   docker compose logs | grep -i sync
   ```

4. Check for stuck records:
   ```bash
   sqlite3 docker-data/queue.db "SELECT * FROM queue WHERE status='pending' LIMIT 5;"
   ```

---

### Queue Database Corrupted

**Error:** `database disk image is malformed`

**Solution (DATA LOSS WARNING):**

1. Backup existing queue:
   ```bash
   cp docker-data/queue.db docker-data/queue.db.backup
   ```

2. Try to recover:
   ```bash
   sqlite3 docker-data/queue.db ".recover" | sqlite3 docker-data/queue_recovered.db
   ```

3. If recovery fails, reset queue (loses pending records):
   ```bash
   rm docker-data/queue.db
   docker compose restart
   ```

---

## Performance Issues

### High Memory Usage

**Troubleshooting:**

1. Check container stats:
   ```bash
   docker stats datang-reader
   ```

2. Set memory limit in `docker-compose.yml`:
   ```yaml
   services:
     datang-reader:
       deploy:
         resources:
           limits:
             memory: 512M
   ```

3. Check queue size:
   ```bash
   sqlite3 docker-data/queue.db "SELECT COUNT(*) FROM queue;"
   ```

---

### Slow Card Processing

**Symptoms:** Delay between card scan and response

**Troubleshooting:**

1. Check API response time:
   ```bash
   time curl -X POST http://localhost:8080/card \
     -H "Content-Type: application/json" \
     -d '{"card_id": "test123"}'
   ```

2. Check network latency:
   ```bash
   ping -c 5 datang.my
   ```

3. Enable debug logging in `server/.env`:
   ```
   DATANG_LOG_LEVEL=DEBUG
   ```

4. Check for database locks:
   ```bash
   lsof docker-data/queue.db
   ```

---

## Python Version Issues

### Python 3.13 Compatibility

Some packages may have issues with Python 3.13. If you encounter build errors:

1. Check Python version:
   ```bash
   python3 --version
   ```

2. Use Python 3.11 or 3.12 instead:
   ```bash
   # Install alternative version
   sudo apt-get install python3.11 python3.11-venv

   # Create venv with specific version
   python3.11 -m venv venv
   ```

---

## Getting Help

If none of these solutions work:

1. **Check logs:**
   - Container: `docker compose logs -f`
   - GUI: `tail -f ~/.datang_reader.log`

2. **Enable debug mode:**
   ```bash
   # In server/.env
   DATANG_LOG_LEVEL=DEBUG
   docker compose restart
   ```

3. **Test in isolation:**
   ```bash
   # Test with mock API
   DATANG_MOCK_API=true ./run-console.sh
   ```

4. **Check system resources:**
   ```bash
   df -h  # Disk space
   free -h  # Memory
   top  # CPU usage
   ```

5. **Report issues:**
   - Include full error messages
   - Include relevant logs
   - Include system info (OS, Python version, etc.)
