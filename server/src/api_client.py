"""
Datang API Client Module

This module handles all HTTP communication with the Datang attendance API.
"""

import requests
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from .config import Config


logger = logging.getLogger(__name__)


class DatangAPIError(Exception):
    """Base exception for Datang API errors"""
    pass


class AuthenticationError(DatangAPIError):
    """Authentication failed"""
    pass


class AttendanceSubmissionError(DatangAPIError):
    """Attendance submission failed"""
    pass


class NetworkError(DatangAPIError):
    """Network connection error"""
    pass


class DatangAPIClient:
    """Client for Datang attendance API"""

    # Error codes the attendance endpoint returns (as a 200-OK body, not a
    # 401/403) that actually mean "your token is dead" — these must trigger a
    # re-login, not be treated as a permanent per-card submission failure.
    AUTH_ERROR_CODES = frozenset({"INVALID_LOGIN", "INVALID_TOKEN", "TOKEN_EXPIRED"})

    def __init__(self, token: Optional[str] = None):
        """
        Initialize API client

        Args:
            token: Authentication token. If None, must login first.
        """
        self.token = token
        self.device_id = Config.DEVICE_ID
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'Datang-Linux-Reader/1.0'
        })

        logger.info(f"Initialized API client (device: {self.device_id})")

    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> str:
        """
        Login and obtain authentication token

        Args:
            username: Reader username (from Datang Dashboard). If None, use config.
            password: Reader password. If None, use config.

        Returns:
            Authentication token

        Raises:
            AuthenticationError: If login fails
            NetworkError: If network error occurs
        """
        username = username or Config.READER_USERNAME
        password = password or Config.READER_PASSWORD

        if not username or not password:
            raise AuthenticationError("Username and password are required")

        logger.info(f"Attempting login for user: {username}")

        # Prepare login request (structure captured from Android app)
        login_data = {
            "version": Config.API_VERSION,
            "username": username,
            "password": password,
            "token": None  # Must be null for initial login
        }

        try:
            url = Config.get_api_url("login")
            logger.debug(f"POST {url}")

            response = self.session.post(
                url,
                json=login_data,
                timeout=Config.HTTP_TIMEOUT
            )

            # Log response for debugging
            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response body: {response.text[:200]}")

            # Check response
            if response.status_code == 200:
                data = response.json()

                # Extract token from response (captured structure)
                # Response format: {"token": "...", "reader_name": "...", "place_name": "...", ...}
                token = data.get("token")

                if token:
                    self.token = token
                    # Log additional info from login response
                    reader_name = data.get("reader_name", "Unknown")
                    place_name = data.get("place_name", "Unknown")
                    logger.info(f"Login successful - Reader: {reader_name}, Place: {place_name}")
                    return token
                else:
                    logger.error(f"No token in response: {data}")
                    raise AuthenticationError("No token in login response")

            elif response.status_code == 401 or response.status_code == 403:
                logger.error(f"Authentication failed: {response.text}")
                raise AuthenticationError(f"Invalid credentials: {response.text}")
            else:
                logger.error(f"Login failed with status {response.status_code}: {response.text}")
                raise AuthenticationError(f"Login failed: {response.text}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during login: {e}")
            raise NetworkError(f"Network error: {e}")
        except ValueError as e:
            logger.error(f"Invalid JSON response: {e}")
            raise AuthenticationError(f"Invalid response format: {e}")

    def submit_attendance(
        self,
        card_id: str,
        timestamp: Optional[datetime] = None,
        temperature: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Submit attendance record

        Args:
            card_id: RFID card ID
            timestamp: Attendance timestamp. If None, use current time.
            temperature: Optional temperature reading

        Returns:
            API response data

        Raises:
            AuthenticationError: If not authenticated
            AttendanceSubmissionError: If submission fails
            NetworkError: If network error occurs
        """
        if not self.token:
            raise AuthenticationError("Not authenticated. Call login() first.")

        timestamp = timestamp or datetime.now()
        logger.info(f"Submitting attendance for card: {card_id[:8]}...")

        # Prepare attendance data (structure captured from Android app)
        # IMPORTANT: Token is sent in BODY, not in Authorization header!
        attendance_data = {
            "version": Config.API_VERSION,
            "token": self.token,  # Token goes in request body
            "qr": None,  # QR code (null if not used)
            "ic": None,  # IC/ID card (null if not used)
            "tag": card_id,  # RFID tag/card ID
            "pid": None,  # Person ID (null if not known)
            "temperature": False  # Temperature reading or False
        }

        # Add temperature if provided and enabled
        if temperature is not None and Config.ENABLE_TEMPERATURE:
            attendance_data["temperature"] = temperature

        try:
            url = Config.get_api_url("attendance")
            logger.debug(f"POST {url}")

            # NOTE: Authentication is in request body, NOT in headers
            # No need to add Authorization header
            response = self.session.post(
                url,
                json=attendance_data,
                timeout=Config.HTTP_TIMEOUT
            )

            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response body: {response.text[:200]}")

            # Check response
            if response.status_code == 200 or response.status_code == 201:
                response_json = response.json()

                # Check if response contains 'data' (success) or 'error' (failure)
                # Success format: {"data": {"pid": "...", "name": "...", "time_text": "...", ...}}
                # Error format: {"error": "...", "message": "..."}

                if "data" in response_json:
                    # Success - extract person info
                    data = response_json["data"]
                    person_name = data.get("name", "Unknown")
                    time_text = data.get("time_text", "")
                    section = data.get("section", "")
                    group = data.get("group", "")

                    logger.info(f"Attendance submitted - {person_name} ({section}, {group}) at {time_text}")
                    return data

                elif "error" in response_json:
                    # Error response (e.g., card not found)
                    error_msg = response_json.get("error", "Unknown error")
                    message = response_json.get("message", "")
                    logger.error(f"Attendance error: {error_msg} - {message}")

                    # Some auth failures come back as HTTP 200 with an error
                    # body (e.g. INVALID_LOGIN) instead of a 401/403. Treat
                    # these as an authentication failure so the service clears
                    # the dead token, re-logins and retries — otherwise they get
                    # misclassified as a permanent submission error and EVERY
                    # scan fails (without even queueing) until the container is
                    # restarted.
                    if str(error_msg).strip().upper() in self.AUTH_ERROR_CODES:
                        self.token = None
                        raise AuthenticationError(f"{error_msg}: {message}")

                    raise AttendanceSubmissionError(f"{error_msg}: {message}")

                else:
                    # Unknown response format
                    logger.warning(f"Unexpected response format: {response_json}")
                    return response_json

            elif response.status_code == 401 or response.status_code == 403:
                logger.error("Authentication token expired or invalid")
                self.token = None
                raise AuthenticationError("Token expired. Re-login required.")

            elif response.status_code == 400:
                error_msg = response.text
                logger.error(f"Bad request: {error_msg}")
                raise AttendanceSubmissionError(f"Invalid data: {error_msg}")

            else:
                logger.error(f"Submission failed with status {response.status_code}: {response.text}")
                raise AttendanceSubmissionError(f"Server error: {response.text}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during submission: {e}")
            raise NetworkError(f"Network error: {e}")
        except ValueError as e:
            logger.error(f"Invalid JSON response: {e}")
            raise AttendanceSubmissionError(f"Invalid response format: {e}")

    def check_connection(self) -> bool:
        """
        Check if API is reachable

        Returns:
            True if API is reachable, False otherwise
        """
        try:
            # Try to reach base URL or status endpoint
            url = Config.API_BASE_URL
            response = self.session.get(url, timeout=5)
            return response.status_code < 500  # Any non-server-error is OK
        except Exception as e:
            logger.debug(f"Connection check failed: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """
        Get API client status

        Returns:
            Dictionary with status information
        """
        return {
            "authenticated": bool(self.token),
            "device_id": self.device_id,
            "api_url": Config.API_BASE_URL,
            "connected": self.check_connection()
        }

    def set_token(self, token: str):
        """
        Set authentication token

        Args:
            token: Authentication token
        """
        self.token = token
        logger.info("Token updated")

    def logout(self):
        """Clear authentication token"""
        self.token = None
        logger.info("Logged out")


class MockAPIClient(DatangAPIClient):
    """
    Mock API client for testing without actual server

    This allows development and testing before capturing real API endpoints.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        logger.warning("Using MOCK API client - responses are simulated!")

    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> str:
        """Mock login - always succeeds"""
        logger.info(f"MOCK: Login for {username or 'default'}")
        self.token = "mock_token_12345"
        return self.token

    def submit_attendance(
        self,
        card_id: str,
        timestamp: Optional[datetime] = None,
        temperature: Optional[float] = None
    ) -> Dict[str, Any]:
        """Mock attendance submission - returns structure matching real API"""
        logger.info(f"MOCK: Attendance for card {card_id}")
        ts = timestamp or datetime.now()
        # Return structure matching captured API response (the 'data' part)
        return {
            "pid": "mock_person_123",
            "time": str(int(ts.timestamp() * 1000)),  # Unix timestamp in milliseconds
            "time_text": ts.strftime("%H:%M:%S %d %B %Y"),
            "image": None,
            "name": "TEST USER (MOCK)",
            "section": "TEST SECTION",
            "group": "Test Group",
            "take_temperature": False,
            "temperature_type": 1,
            "week": 1,
            "temperature": temperature if temperature else False
        }

    def check_connection(self) -> bool:
        """Mock connection check - always returns True"""
        return True
