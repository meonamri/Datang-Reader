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


class Config:
    """GUI Client Configuration"""

    # Server connection
    CONTAINER_URL = os.getenv("DATANG_CONTAINER_URL", "http://localhost:8080")

    # Window settings
    WINDOW_WIDTH = 800
    WINDOW_HEIGHT = 600
    FULLSCREEN = os.getenv("DATANG_FULLSCREEN", "true").lower() == "true"

    # Animation settings
    ENABLE_PULSE_ANIMATION = os.getenv("DATANG_ENABLE_PULSE", "true").lower() == "true"
    PULSE_ANIMATION_FPS = 12  # Updates per second (lower = less CPU usage for ARM)
