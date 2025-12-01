"""
Authentication Manager Module

This module handles authentication token storage, retrieval, and auto-login.
"""

import os
import json
import logging
from typing import Optional
from datetime import datetime, timedelta
from .config import Config
from .api_client import DatangAPIClient, AuthenticationError, NetworkError


logger = logging.getLogger(__name__)


class AuthManager:
    """Manages authentication and token persistence"""

    def __init__(self, api_client: DatangAPIClient):
        """
        Initialize authentication manager

        Args:
            api_client: Datang API client instance
        """
        self.api_client = api_client
        self.token_file = Config.TOKEN_FILE
        logger.info(f"Initialized auth manager (token file: {self.token_file})")

    def load_token(self) -> bool:
        """
        Load saved authentication token from file

        Returns:
            True if token loaded successfully, False otherwise
        """
        if not os.path.exists(self.token_file):
            logger.debug("No saved token file found")
            return False

        try:
            with open(self.token_file, 'r') as f:
                data = json.load(f)

            token = data.get('token')
            saved_at = data.get('saved_at')
            device_id = data.get('device_id')

            if not token:
                logger.warning("Token file exists but contains no token")
                return False

            # Check if token is for this device
            if device_id != Config.DEVICE_ID:
                logger.warning(f"Token is for different device ({device_id}), ignoring")
                return False

            # Check token age (optional - if you know token lifetime)
            if saved_at:
                token_age = datetime.now() - datetime.fromisoformat(saved_at)
                logger.debug(f"Token age: {token_age}")
                # You might want to check if token is too old here

            self.api_client.set_token(token)
            logger.info("Loaded saved authentication token")
            return True

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse token file: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error loading token: {e}")
            return False

    def save_token(self, token: str) -> bool:
        """
        Save authentication token to file

        Args:
            token: Authentication token to save

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            data = {
                'token': token,
                'saved_at': datetime.now().isoformat(),
                'device_id': Config.DEVICE_ID
            }

            # Create directory if needed
            token_dir = os.path.dirname(self.token_file)
            if token_dir and not os.path.exists(token_dir):
                try:
                    os.makedirs(token_dir, mode=0o700)
                except (OSError, TypeError):
                    # Windows doesn't support Unix permissions, use defaults
                    os.makedirs(token_dir)

            # Write token file
            with open(self.token_file, 'w') as f:
                json.dump(data, f, indent=2)

            # Set restrictive permissions (readable only by owner)
            try:
                os.chmod(self.token_file, 0o600)
            except (OSError, TypeError):
                # Windows doesn't support Unix permissions
                logger.debug("File permissions not set (Windows/non-Unix platform)")

            logger.info("Saved authentication token")
            return True

        except Exception as e:
            logger.error(f"Failed to save token: {e}")
            return False

    def clear_token(self):
        """Remove saved token file"""
        if os.path.exists(self.token_file):
            try:
                os.remove(self.token_file)
                logger.info("Cleared saved token")
            except Exception as e:
                logger.error(f"Failed to remove token file: {e}")

    def ensure_authenticated(self, force_login: bool = False) -> bool:
        """
        Ensure API client is authenticated, login if necessary

        Args:
            force_login: Force fresh login even if token exists

        Returns:
            True if authenticated, False if login failed
        """
        # Check if already authenticated
        if not force_login and self.api_client.token:
            logger.debug("Already authenticated")
            return True

        # Try to load saved token
        if not force_login and self.load_token():
            logger.info("Using saved authentication token")
            # TODO: Optionally verify token is still valid with API call
            return True

        # Need to login
        logger.info("No valid token, performing login...")
        return self.login()

    def login(self) -> bool:
        """
        Perform login and save token

        Returns:
            True if login successful, False otherwise
        """
        try:
            token = self.api_client.login()
            if token:
                self.save_token(token)
                logger.info("Login successful, token saved")
                return True
            else:
                logger.error("Login returned no token")
                return False

        except AuthenticationError as e:
            logger.error(f"Authentication failed: {e}")
            # Clear invalid saved token
            self.clear_token()
            return False

        except NetworkError as e:
            logger.error(f"Network error during login: {e}")
            # Don't clear token - might be temporary network issue
            return False

        except Exception as e:
            logger.error(f"Unexpected error during login: {e}")
            return False

    def logout(self):
        """Logout and clear saved token"""
        self.api_client.logout()
        self.clear_token()
        logger.info("Logged out")

    def verify_credentials(self) -> tuple[bool, Optional[str]]:
        """
        Verify that credentials are configured

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not Config.READER_USERNAME:
            return False, "READER_USERNAME not configured"

        if not Config.READER_PASSWORD:
            return False, "READER_PASSWORD not configured"

        return True, None
