"""
Configuration module for Datang Reader Linux Service

This file contains all configuration settings for the service.
Fill in the values after capturing API endpoints using the network interception guide.
"""

import os
import json
from typing import Dict, Any


class Config:
    """Configuration settings for Datang Reader Service"""

    # ===== API CONFIGURATION =====
    # CAPTURED FROM LIVE TRAFFIC - See API_ENDPOINTS_CAPTURED.md for details

    # Base API URL
    API_BASE_URL = os.getenv("DATANG_API_URL", "https://datang.my/api/reader/v1")

    # API Version (sent in all requests)
    API_VERSION = 1

    # API Endpoints (captured from Android app network traffic)
    API_ENDPOINTS = {
        "login": "/login",
        "attendance": "/scan",  # NOTE: endpoint is /scan, not /confirmAttendance
        # Note: Other endpoints like /status, /sync may exist but weren't captured yet
    }

    # ===== AUTHENTICATION =====

    # IMPORTANT: This API uses BODY-based authentication, not headers!
    # The token is passed as a JSON field in the request body, not in Authorization header.
    # The AUTH_HEADER_* settings below are kept for potential future use but are NOT currently used.

    # Reader credentials (get from Datang Dashboard)
    # Format: {organization_id}_reader{number}
    # SECURITY: These MUST be set via environment variables - no defaults provided
    # Set DATANG_READER_USERNAME and DATANG_READER_PASSWORD before running
    READER_USERNAME = os.getenv("DATANG_READER_USERNAME")
    READER_PASSWORD = os.getenv("DATANG_READER_PASSWORD")

    # Device identification (not currently used by API, but kept for future use)
    DEVICE_ID = os.getenv("DATANG_DEVICE_ID", "linux-reader-001")

    # Token storage location
    TOKEN_FILE = os.path.expanduser("~/.datang_reader_token")

    # Authentication header format (NOT USED - token goes in request body)
    # Kept for reference in case API changes in future
    AUTH_HEADER_FORMAT = "Bearer {token}"
    AUTH_HEADER_NAME = "Authorization"

    # ===== USB RFID READER CONFIGURATION =====

    # Serial port (auto-detect if empty, or specify like /dev/ttyUSB0)
    SERIAL_PORT = os.getenv("DATANG_SERIAL_PORT", "")

    # Baud rate (common: 9600, 115200)
    SERIAL_BAUD_RATE = int(os.getenv("DATANG_SERIAL_BAUD", "9600"))

    # Serial timeout in seconds
    SERIAL_TIMEOUT = 1.0

    # Read timeout - how long to wait for card scan
    CARD_READ_TIMEOUT = 30

    # Data format settings
    CARD_DATA_ENCODING = "ascii"  # or "utf-8"
    CARD_DATA_STRIP_CHARS = "\r\n\x00"  # Characters to strip from card data

    # ===== OFFLINE QUEUE CONFIGURATION =====

    # Database file for offline attendance queue
    DATABASE_FILE = os.path.expanduser("~/.datang_reader_queue.db")

    # Maximum queue size
    MAX_QUEUE_SIZE = 10000

    # Retry settings
    RETRY_INTERVAL = 60  # seconds between retry attempts
    MAX_RETRY_ATTEMPTS = 5

    # ===== GUI CONFIGURATION =====

    # Window settings
    WINDOW_TITLE = "Datang Reader - Attendance System"
    WINDOW_WIDTH = 800
    WINDOW_HEIGHT = 600
    FULLSCREEN = os.getenv("DATANG_FULLSCREEN", "false").lower() == "true"

    # Display settings
    SHOW_CARD_ID = False  # Whether to display full card ID on screen
    SUCCESS_DISPLAY_TIME = 3  # seconds to show success message
    ERROR_DISPLAY_TIME = 5  # seconds to show error message

    # Sound feedback
    ENABLE_SOUND = True
    SUCCESS_SOUND = "success.wav"  # Optional sound file
    ERROR_SOUND = "error.wav"  # Optional sound file

    # ===== LOGGING CONFIGURATION =====

    # Log file location
    LOG_FILE = os.path.expanduser("~/.datang_reader.log")

    # Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    LOG_LEVEL = os.getenv("DATANG_LOG_LEVEL", "INFO")

    # Log rotation
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
    LOG_BACKUP_COUNT = 5

    # ===== ADVANCED SETTINGS =====

    # Network timeout
    HTTP_TIMEOUT = 30  # seconds

    # Connection check interval
    CONNECTION_CHECK_INTERVAL = 300  # seconds (5 minutes)

    # Duplicate scan prevention (ignore same card within this time)
    DUPLICATE_SCAN_WINDOW = 5  # seconds

    # Temperature sensor (if supported)
    ENABLE_TEMPERATURE = False
    TEMPERATURE_UNIT = "celsius"  # or "fahrenheit"

    @classmethod
    def get_api_url(cls, endpoint: str) -> str:
        """
        Get full API URL for an endpoint

        Args:
            endpoint: Endpoint key (e.g., "login", "attendance")

        Returns:
            Full URL
        """
        endpoint_path = cls.API_ENDPOINTS.get(endpoint, "")
        return f"{cls.API_BASE_URL}{endpoint_path}"

    @classmethod
    def get_auth_header(cls, token: str) -> Dict[str, str]:
        """
        Get authentication header with token

        Args:
            token: Authentication token

        Returns:
            Dictionary with auth header
        """
        header_value = cls.AUTH_HEADER_FORMAT.format(token=token)
        return {cls.AUTH_HEADER_NAME: header_value}

    @classmethod
    def load_from_file(cls, config_file: str):
        """
        Load configuration from JSON file

        Args:
            config_file: Path to configuration file
        """
        if not os.path.exists(config_file):
            return

        with open(config_file, 'r') as f:
            config_data = json.load(f)

        # Update class attributes
        for key, value in config_data.items():
            if hasattr(cls, key):
                setattr(cls, key, value)

    @classmethod
    def save_to_file(cls, config_file: str):
        """
        Save configuration to JSON file

        Args:
            config_file: Path to configuration file
        """
        config_data = {
            "API_BASE_URL": cls.API_BASE_URL,
            "API_ENDPOINTS": cls.API_ENDPOINTS,
            "READER_USERNAME": cls.READER_USERNAME,
            "READER_PASSWORD": cls.READER_PASSWORD,
            "DEVICE_ID": cls.DEVICE_ID,
            "SERIAL_PORT": cls.SERIAL_PORT,
            "SERIAL_BAUD_RATE": cls.SERIAL_BAUD_RATE,
            "AUTH_HEADER_FORMAT": cls.AUTH_HEADER_FORMAT,
            "AUTH_HEADER_NAME": cls.AUTH_HEADER_NAME,
        }

        with open(config_file, 'w') as f:
            json.dump(config_data, f, indent=2)

    @classmethod
    def validate(cls) -> tuple[bool, list[str]]:
        """
        Validate configuration

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        if not cls.API_BASE_URL:
            errors.append("API_BASE_URL is not set")

        if not cls.READER_USERNAME:
            errors.append(
                "READER_USERNAME is not set. "
                "Set the DATANG_READER_USERNAME environment variable with your reader username "
                "(format: {organization_id}_reader{number})"
            )

        if not cls.READER_PASSWORD:
            errors.append(
                "READER_PASSWORD is not set. "
                "Set the DATANG_READER_PASSWORD environment variable with your reader password"
            )

        if not cls.DEVICE_ID:
            errors.append("DEVICE_ID is not set")

        return len(errors) == 0, errors


# ===== CONFIGURATION TEMPLATE FOR API CAPTURE =====
# Copy this template to api_config.json and fill in after capturing traffic

CONFIG_TEMPLATE = {
    "API_BASE_URL": "https://datang.my/api/reader/v1",
    "API_VERSION": 1,
    "API_ENDPOINTS": {
        "login": "/login",
        "attendance": "/scan"  # Captured endpoint
    },
    "AUTH_HEADER_FORMAT": "Bearer {token}",  # NOT USED - token goes in body
    "AUTH_HEADER_NAME": "Authorization",  # NOT USED - token goes in body
    # SECURITY: Do NOT put credentials in config files - use environment variables instead
    # "READER_USERNAME": "use_environment_variable_instead",
    # "READER_PASSWORD": "use_environment_variable_instead",
    "DEVICE_ID": "linux-reader-001",
    "SERIAL_PORT": "/dev/ttyUSB0",
    "SERIAL_BAUD_RATE": 9600
}
