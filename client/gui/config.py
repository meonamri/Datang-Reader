"""
GUI Client Configuration

GUI-specific settings for the PyQt5 input client.
"""

import os


def _load_env_file():
    """Load .env file from the client directory if not already in environment.

    This provides a reliable fallback when the shell script's 'source .env'
    fails (e.g., due to CRLF line endings or other encoding issues).
    """
    gui_dir = os.path.dirname(os.path.abspath(__file__))
    client_dir = os.path.dirname(gui_dir)  # Go up from gui/ to client/
    env_path = os.path.join(client_dir, '.env')

    if not os.path.isfile(env_path):
        return

    try:
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip()
                # Remove surrounding quotes if present
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                # Don't override existing env vars (shell exports take precedence)
                if key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass


_load_env_file()


# ===== Smartt naming (renamed from "Datang Reader", 2026-11) =====
# Smartt is this school-owned service; Datang.my is the vendor attendance API it
# talks to. Settings that belong to Smartt were renamed DATANG_* -> SMARTT_* and
# its state files ~/.datang_* -> ~/.smartt_*. The old names keep working:

_SQLITE_SIDECARS = ("-wal", "-shm", "-journal")


def env(name: str, legacy: str = None, default: str = None):
    """os.getenv(name), falling back to the pre-rename variable `legacy`."""
    value = os.getenv(name)
    if value is None and legacy:
        value = os.getenv(legacy)
    return default if value is None else value


def state_path(new: str, legacy: str) -> str:
    """Path of a renamed state file, migrating the legacy file on first use.

    The new path wins when it exists (or when neither exists). Otherwise the
    legacy file is renamed to the new path. A legacy SQLite database with a
    -wal/-shm/-journal sidecar was not closed cleanly, so it is used where it is
    rather than split from its journal; so is any file the rename fails on.
    """
    new, legacy = os.path.expanduser(new), os.path.expanduser(legacy)
    if os.path.exists(new) or not os.path.exists(legacy):
        return new
    if any(os.path.exists(legacy + s) for s in _SQLITE_SIDECARS):
        return legacy
    try:
        os.replace(legacy, new)
        return new
    except OSError:
        return legacy


class Config:
    """GUI Client Configuration"""

    # Server connection
    CONTAINER_URL = env("SMARTT_CONTAINER_URL", "DATANG_CONTAINER_URL", "http://localhost:8080")

    # Window settings
    WINDOW_WIDTH = 800
    WINDOW_HEIGHT = 600
    FULLSCREEN = env("SMARTT_FULLSCREEN", "DATANG_FULLSCREEN", "true").lower() == "true"

    # Animation settings
    ENABLE_PULSE_ANIMATION = env("SMARTT_ENABLE_PULSE", "DATANG_ENABLE_PULSE", "true").lower() == "true"
    PULSE_ANIMATION_FPS = int(env("SMARTT_PULSE_FPS", "DATANG_PULSE_FPS", "30"))
