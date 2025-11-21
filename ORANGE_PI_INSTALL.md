# Orange Pi / Low-Memory ARM Device Installation Guide

## Your Installation is Stuck? Here's What to Do

### Quick Fix (5 minutes)

Your Orange Pi Zero 3 installation is hanging because PyQt5 is compiling from source (30-60+ min). Follow these steps:

#### 1. Cancel the Stuck Installation
```bash
# Press Ctrl+C in the terminal where install.sh is running
```

#### 2. Clean Up
```bash
cd /path/to/Datang-Reader
rm -rf venv  # Remove the incomplete virtual environment
```

#### 3. Pull Latest Changes
```bash
git pull origin main
```

#### 4. Run the Updated Installer
```bash
./install.sh
```

#### 5. When Prompted, Answer 'y'
The installer will ask:
```
Install system dependencies with sudo? (y/N):
```
**Answer: `y`**

This installs pre-compiled PyQt5 from DietPi's package manager (instant, no compilation).

---

## What Changed?

The updated `install.sh` (2025-11-21) now:

✅ **Detects ARM devices** and warns about PyQt5 compilation issues
✅ **Uses system PyQt5** (pre-compiled) instead of compiling from source
✅ **Shows progress** - no more silent "stuck" appearance
✅ **Fast installation** - completes in 2-3 minutes instead of 30-60 minutes
✅ **Lower memory usage** - works reliably on 1GB RAM devices

---

## Installation Process Overview

### What Will Happen:

1. **Check for Python** → ✓ Found Python 3.x
2. **Check for Qt5 libraries** → Prompt to install system packages
3. **Install system packages** (you answer 'y'):
   ```
   sudo apt-get install python3-pyqt5 qtbase5-dev python3-dev
   ```
   Takes: ~30 seconds
4. **Create venv with system access**:
   ```
   python3 -m venv --system-site-packages venv
   ```
5. **Install remaining dependencies** (requests, pystray, Pillow):
   ```
   pip install requests pystray Pillow
   ```
   Takes: ~1-2 minutes
6. **Create launcher scripts** (run-gui.sh, run-console.sh)
7. **Done!** Total time: ~3-5 minutes

### What You'll See:

```
================================================================
Checking System Dependencies
================================================================

Checking for Qt5 development libraries...
Qt5 libraries not found. Installation requires sudo.

IMPORTANT: For ARM devices (Raspberry Pi, Orange Pi, etc.) with limited RAM,
we recommend using system-provided PyQt5 packages instead of compiling from source.

The following packages will be installed:
  - python3-pyqt5 (Pre-compiled PyQt5 - recommended for ARM)
  - qtbase5-dev (Qt5 development libraries)
  - python3-dev (Python development headers)

Benefits:
  ✓ Instant installation (no 30-60 min compilation)
  ✓ Lower memory usage during installation
  ✓ Pre-tested and optimized for your platform

Install system dependencies with sudo? (y/N): █
```

---

## After Installation

### Test the GUI Client

```bash
# Make sure Docker container is running first
docker compose ps

# Launch the GUI
./run-gui.sh
```

### If You Get "ModuleNotFoundError: No module named 'PyQt5'"

This means the venv can't see the system PyQt5. Check:

```bash
# Verify system PyQt5 is installed
dpkg -l | grep python3-pyqt5

# Verify venv has system-site-packages enabled
cat venv/pyvenv.cfg | grep system-site-packages
# Should say: include-system-site-packages = true

# Test PyQt5 import
source venv/bin/activate
python3 -c "from PyQt5.QtWidgets import QApplication; print('PyQt5 OK')"
```

If still not working, recreate venv:
```bash
rm -rf venv
./install.sh
```

---

## Why Was It Hanging?

### The Problem

On ARM devices like Orange Pi Zero 3:
- PyQt5 has no pre-compiled wheel (binary package)
- pip must compile PyQt5 from C++ source code
- Compilation requires:
  - 30-60+ minutes (slow ARM CPU)
  - 2GB+ RAM (1GB barely sufficient, uses swap heavily)
  - Build tools (gcc, g++, make, etc.)

The old script used `pip install -q` (quiet mode), which hid all compilation output. It looked "stuck" but was actually compiling slowly in the background.

### The Solution

Use system-provided PyQt5:
- ✅ Pre-compiled binary (no compilation needed)
- ✅ Optimized for your specific ARM architecture
- ✅ Tested and maintained by DietPi/Debian
- ✅ Installs in 30 seconds via apt-get
- ✅ Lower memory footprint

The venv uses `--system-site-packages` to access the system PyQt5 while keeping other packages isolated.

---

## Troubleshooting

### "Package python3-pyqt5 not found"

Update your package list:
```bash
sudo apt-get update
sudo apt-get install python3-pyqt5
```

### "Permission denied" when installing system packages

Run the installer as a regular user (not root). It will ask for sudo password when needed:
```bash
# Don't do this:
sudo ./install.sh

# Do this:
./install.sh
```

### Still want to compile PyQt5 from source?

Not recommended for 1GB RAM devices, but possible:

```bash
# Increase swap space first (2GB+)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Run installer and decline system packages
./install.sh
# Answer 'n' to system packages
# Answer 'y' to "Continue anyway?"
# Wait 60+ minutes for compilation
```

---

## Summary

**Old method:** PyQt5 compilation (30-60 min, high memory, often fails)
**New method:** System PyQt5 packages (instant, reliable, recommended)

**Your next steps:**
1. Cancel stuck installation (Ctrl+C)
2. `rm -rf venv`
3. `git pull origin main`
4. `./install.sh` (answer 'y' to install system packages)
5. `./run-gui.sh` (after Docker container is running)

Installation should complete in ~3-5 minutes instead of hanging!
