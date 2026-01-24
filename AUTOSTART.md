# Auto-start GUI on Boot

This guide explains how to configure the Datang Reader GUI to automatically launch when your system boots.

## Quick Setup

### 1. Install GUI Client (if not done already)

```bash
cd client/
./install.sh
```

### 2. Install Auto-start Service

```bash
cd client/
./install-autostart.sh
```

Follow the prompts:
- **Enable lingering**: Choose `y` if you want the GUI to run on boot without desktop login
- **Start now**: Choose `y` to start the service immediately

### 3. Ensure Docker Server is Running

```bash
cd server/
docker compose up -d
```

That's it! The GUI will now automatically start on boot.

---

## Service Management

### Check Status

```bash
systemctl --user status datang-reader-gui
```

### View Logs

```bash
# Live log streaming
journalctl --user -u datang-reader-gui -f

# Last 100 lines
journalctl --user -u datang-reader-gui -n 100
```

### Start/Stop/Restart

```bash
# Start
systemctl --user start datang-reader-gui

# Stop
systemctl --user stop datang-reader-gui

# Restart
systemctl --user restart datang-reader-gui
```

### Disable Auto-start

```bash
systemctl --user disable datang-reader-gui
```

To completely remove:

```bash
systemctl --user disable datang-reader-gui
systemctl --user stop datang-reader-gui
rm ~/.config/systemd/user/datang-reader-gui.service
systemctl --user daemon-reload
```

---

## Manual Setup (Alternative Method)

If you prefer to install manually:

### 1. Copy Service File

```bash
mkdir -p ~/.config/systemd/user
cp systemd/datang-reader-gui.service ~/.config/systemd/user/
```

### 2. Update Paths in Service File

Edit `~/.config/systemd/user/datang-reader-gui.service` and replace `/home/user` with your actual home directory.

### 3. Enable Service

```bash
systemctl --user daemon-reload
systemctl --user enable datang-reader-gui
systemctl --user start datang-reader-gui
```

---

## Troubleshooting

### GUI doesn't appear after boot

**Check service status:**
```bash
systemctl --user status datang-reader-gui
```

**Check logs:**
```bash
journalctl --user -u datang-reader-gui -n 50
```

**Common issues:**

1. **Display not set correctly**
   - Check DISPLAY variable: `echo $DISPLAY` (should be `:0` or `:1`)
   - Edit service file and update DISPLAY value

2. **Docker server not running**
   ```bash
   cd server/ && docker compose up -d
   ```

3. **GUI starts before X11 is ready**
   - Increase sleep time in service file (edit `ExecStartPre=/bin/sleep 10` to higher value)

### GUI runs but can't connect to server

**Verify Docker server:**
```bash
curl http://localhost:8080/health
```

**Check Docker container:**
```bash
cd server/
docker compose ps
docker compose logs
```

### Disable service temporarily

```bash
systemctl --user stop datang-reader-gui
```

### Service runs even when logged out

This happens if you enabled "lingering". To disable:

```bash
loginctl disable-linger $USER
```

---

## Architecture

```
System Boot
    ↓
User Login to Desktop (graphical.target)
    ↓
Systemd User Service Starts
    ↓
run-gui.sh launches
    ↓
PyQt5 GUI appears
    ↓
Connects to Docker server (localhost:8080)
    ↓
Ready to scan RFID cards
```

---

## Environment Variables

The service uses these environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DISPLAY` | `:0` | X11 display server |
| `QT_QPA_PLATFORM` | `xcb` | Qt platform plugin (X11) |
| `XAUTHORITY` | `~/.Xauthority` | X11 authentication file |
| `PYTHONUNBUFFERED` | `1` | Disable Python output buffering |

To customize, edit `~/.config/systemd/user/datang-reader-gui.service`

---

## Advanced Configuration

### Run on Multiple Displays

If you have multiple displays, you can create multiple service instances:

```bash
# Copy service file
cp ~/.config/systemd/user/datang-reader-gui.service \
   ~/.config/systemd/user/datang-reader-gui@.service
```

Edit and change:
```ini
[Service]
ExecStart=/home/user/Datang-Reader/client/run-gui.sh --url http://localhost:808%i
Environment="DISPLAY=:%i"
```

Enable for DISPLAY :0 and :1:
```bash
systemctl --user enable datang-reader-gui@0
systemctl --user enable datang-reader-gui@1
```

### Custom Container URL

Edit service file and add to `[Service]` section:

```ini
Environment="DATANG_CONTAINER_URL=http://192.168.1.100:8080"
```

Then modify `ExecStart`:
```ini
ExecStart=/home/user/Datang-Reader/client/run-gui.sh --url ${DATANG_CONTAINER_URL}
```

### Auto-start Docker Server

To ensure Docker server starts automatically:

```bash
cd server/
docker compose up -d

# Enable auto-restart
docker update --restart unless-stopped $(docker compose ps -q)
```

---

## Security Considerations

1. **Service runs as your user** - No root privileges needed
2. **X11 access** - Service needs access to your X display
3. **USB RFID reader** - Ensure user has permissions (usually automatic for desktop users)
4. **Credentials** - Stored in `/path/to/project/.env` (check permissions: `chmod 600 .env`)

---

## See Also

- [README.md](README.md) - Main documentation
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Troubleshooting guide
- [systemd/datang-reader-gui.service](systemd/datang-reader-gui.service) - Service file template
