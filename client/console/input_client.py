#!/usr/bin/env python3
"""
Input Client for Datang Reader

Lightweight script that runs on the host to capture HID RFID reader input
and forward it to the Datang Reader server via HTTP.

This script:
1. Reads keyboard input from stdin (HID RFID reader types card ID + Enter)
2. Validates the 10-digit format
3. POSTs card ID to the server's HTTP endpoint
4. Handles connection errors with retry logic
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime
from typing import Optional

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library not found.", file=sys.stderr)
    print("Install it with: pip install requests", file=sys.stderr)
    sys.exit(1)


# Configuration
DEFAULT_CONTAINER_URL = os.getenv("DATANG_CONTAINER_URL", "http://localhost:8080")
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
REQUEST_TIMEOUT = 5  # seconds


class InputClient:
    """RFID input client that forwards card scans to the Datang Reader server"""

    def __init__(self, container_url: str, log_file: Optional[str] = None):
        """
        Initialize input client

        Args:
            container_url: Base URL of the server (e.g., http://localhost:8080)
            log_file: Optional log file path
        """
        self.container_url = container_url.rstrip('/')
        self.card_endpoint = f"{self.container_url}/card"
        self.health_endpoint = f"{self.container_url}/health"
        self.running = False

        # Setup logging
        self.logger = logging.getLogger('InputClient')
        self._setup_logging(log_file)

    def _setup_logging(self, log_file: Optional[str]):
        """Setup logging configuration"""
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        # File handler if specified
        if log_file:
            try:
                file_handler = logging.FileHandler(log_file)
                file_handler.setFormatter(formatter)
                self.logger.addHandler(file_handler)
            except Exception as e:
                self.logger.warning(f"Could not setup file logging: {e}")

        self.logger.setLevel(logging.INFO)

    def check_container_health(self) -> bool:
        """
        Check if container is reachable and healthy

        Returns:
            True if healthy, False otherwise
        """
        try:
            response = requests.get(
                self.health_endpoint,
                timeout=REQUEST_TIMEOUT
            )
            return response.status_code == 200
        except Exception as e:
            self.logger.debug(f"Health check failed: {e}")
            return False

    def send_card_scan(self, card_id: str, temperature: Optional[float] = None) -> bool:
        """
        Send card scan to server with retry logic

        Args:
            card_id: 10-digit card ID
            temperature: Optional temperature reading

        Returns:
            True if successfully sent, False otherwise
        """
        payload = {"card_id": card_id}
        if temperature is not None:
            payload["temperature"] = temperature

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = requests.post(
                    self.card_endpoint,
                    json=payload,
                    timeout=REQUEST_TIMEOUT
                )

                if response.status_code == 200:
                    result = response.json()
                    if result.get('success'):
                        status = "ONLINE" if result.get('online') else "OFFLINE"
                        message = result.get('message', 'Recorded')
                        self.logger.info(f"✓ Card {card_id[:8]}... [{status}] {message}")
                        return True
                    else:
                        self.logger.error(f"✗ Card {card_id[:8]}... ERROR: {result.get('message')}")
                        return False
                else:
                    self.logger.error(f"Server returned status {response.status_code}")

            except requests.exceptions.ConnectionError:
                if attempt < MAX_RETRIES:
                    self.logger.warning(f"Server unreachable, retry {attempt}/{MAX_RETRIES}...")
                    time.sleep(RETRY_DELAY)
                else:
                    self.logger.error(f"✗ Failed to reach server after {MAX_RETRIES} attempts")
                    return False

            except requests.exceptions.Timeout:
                if attempt < MAX_RETRIES:
                    self.logger.warning(f"Request timeout, retry {attempt}/{MAX_RETRIES}...")
                    time.sleep(RETRY_DELAY)
                else:
                    self.logger.error(f"✗ Request timeout after {MAX_RETRIES} attempts")
                    return False

            except Exception as e:
                self.logger.error(f"✗ Unexpected error: {e}")
                return False

        return False

    def validate_card_id(self, card_id: str) -> bool:
        """
        Validate card ID format

        Args:
            card_id: Card ID to validate

        Returns:
            True if valid, False otherwise
        """
        card_id = card_id.strip()

        if not card_id:
            return False

        if not card_id.isdigit():
            self.logger.warning(f"Invalid card ID (not all digits): '{card_id}'")
            return False

        if len(card_id) != 10:
            self.logger.warning(f"Invalid card ID (expected 10 digits, got {len(card_id)}): '{card_id}'")
            return False

        return True

    def run(self):
        """
        Main loop: read card IDs from stdin and forward to container

        Reads keyboard input (HID RFID reader types card ID + Enter)
        and forwards valid scans to the server.
        """
        self.logger.info("="*60)
        self.logger.info("Datang Reader - Input Client")
        self.logger.info("="*60)
        self.logger.info(f"Server URL: {self.container_url}")

        # Show URL source for troubleshooting
        env_url = os.getenv("DATANG_CONTAINER_URL")
        if env_url:
            self.logger.info("(configured via DATANG_CONTAINER_URL)")
        elif self.container_url != "http://localhost:8080":
            self.logger.info("(configured via --url)")
        else:
            self.logger.info("(using default URL)")

        self.logger.info("Checking server health...")

        # Initial health check
        if not self.check_container_health():
            self.logger.error("Server is not reachable or unhealthy!")
            if not env_url and self.container_url == "http://localhost:8080":
                self.logger.error("You are using the default URL (http://localhost:8080).")
                self.logger.error("If your server is running elsewhere, configure the URL:")
                self.logger.error("  1. Copy .env.example to .env and edit DATANG_CONTAINER_URL")
                self.logger.error("  2. Or run with: ./run-console.sh --url <server-url>")
            else:
                self.logger.error(f"Make sure the server at {self.container_url} is running.")
            self.logger.error("Continuing anyway (will retry on each scan)...")
        else:
            self.logger.info("Server is healthy ✓")

        self.logger.info("="*60)
        self.logger.info("Ready to capture RFID card scans")
        self.logger.info("Scan RFID card (reader will type the card ID)")
        self.logger.info("Press Ctrl+C to quit")
        self.logger.info("="*60)

        self.running = True

        try:
            while self.running:
                try:
                    # Read line from stdin (HID reader types card ID + Enter)
                    card_id = input().strip()

                    if not card_id:
                        continue  # Empty line, skip

                    # Validate format
                    if not self.validate_card_id(card_id):
                        continue

                    # Send to container
                    timestamp = datetime.now().strftime('%H:%M:%S')
                    self.logger.info(f"[{timestamp}] Card scanned: {card_id}")
                    self.send_card_scan(card_id)

                except EOFError:
                    # EOF reached (Ctrl+D on Unix, Ctrl+Z on Windows)
                    self.logger.info("EOF received, exiting...")
                    break

        except KeyboardInterrupt:
            self.logger.info("\nShutdown signal received...")
        finally:
            self.running = False
            self.logger.info("Input client stopped")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='RFID Input Client for Datang Reader'
    )
    parser.add_argument(
        '--url',
        default=DEFAULT_CONTAINER_URL,
        help=f'Server URL (default: {DEFAULT_CONTAINER_URL})'
    )
    parser.add_argument(
        '--log-file',
        help='Log file path (default: stdout only)'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )

    args = parser.parse_args()

    # Create and run client
    client = InputClient(
        container_url=args.url,
        log_file=args.log_file
    )

    if args.debug:
        client.logger.setLevel(logging.DEBUG)

    client.run()


if __name__ == '__main__':
    main()
