"""
GUI Client Configuration

GUI-specific settings for the PyQt5 input client.
"""

import os


class Config:
    """GUI Client Configuration"""

    # Window settings
    WINDOW_WIDTH = 800
    WINDOW_HEIGHT = 600
    FULLSCREEN = os.getenv("DATANG_FULLSCREEN", "true").lower() == "true"

    # Animation settings
    ENABLE_PULSE_ANIMATION = os.getenv("DATANG_ENABLE_PULSE", "true").lower() == "true"
    PULSE_ANIMATION_FPS = 12  # Updates per second (lower = less CPU usage for ARM)
