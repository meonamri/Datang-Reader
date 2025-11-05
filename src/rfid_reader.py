"""
USB RFID Reader Module for Datang Reader Linux Service

This module handles communication with HID keyboard-based RFID readers.
These readers type the card ID as keyboard input when a card is scanned.
"""

import time
import logging
from typing import Optional
from datetime import datetime, timedelta
from queue import Queue, Empty
from .config import Config


logger = logging.getLogger(__name__)


class RFIDReader:
    """HID Keyboard-based RFID Reader Interface"""

    def __init__(self, port: Optional[str] = None, baud_rate: Optional[int] = None):
        """
        Initialize RFID reader

        Args:
            port: Not used for HID readers (kept for compatibility)
            baud_rate: Not used for HID readers (kept for compatibility)
        """
        # Keep these for compatibility but they're not used
        self.port = "HID Keyboard"
        self.baud_rate = None
        self.is_connected = False
        self.last_card_id: Optional[str] = None
        self.last_scan_time: Optional[datetime] = None

        # Queue for card IDs (used for thread-safe communication)
        self.card_queue = Queue()

        logger.info(f"Initializing HID keyboard RFID reader")

    def connect(self) -> bool:
        """
        Connect to RFID reader

        For HID keyboards, this always succeeds since the keyboard is always available.

        Returns:
            True (HID keyboards are always available)
        """
        self.is_connected = True
        logger.info(f"Connected to HID keyboard RFID reader")
        return True

    def disconnect(self):
        """Disconnect from RFID reader"""
        self.is_connected = False
        logger.info("Disconnected from RFID reader")

    def push_card_id(self, card_id: str):
        """
        Push a card ID into the queue (called by GUI/console when card is scanned)

        Args:
            card_id: Card ID string from keyboard input
        """
        if card_id and card_id.strip():
            self.card_queue.put(card_id.strip())

    def read_card(self, timeout: Optional[int] = None) -> Optional[str]:
        """
        Read RFID card data from queue

        This method waits for a card ID to be pushed into the queue via push_card_id().
        Used in console mode and for compatibility with existing code.

        Args:
            timeout: Read timeout in seconds. If None, use config default.

        Returns:
            Card ID as string, or None if timeout or error
        """
        if not self.is_connected:
            logger.error("RFID reader not connected")
            return None

        timeout = timeout or Config.CARD_READ_TIMEOUT

        try:
            # Wait for card ID from queue
            card_id = self.card_queue.get(timeout=timeout)

            # Process the card ID
            card_id = self._process_card_data(card_id)

            # Check for duplicate scan
            if self._is_duplicate_scan(card_id):
                logger.warning(f"Duplicate scan ignored: {card_id}")
                return None

            # Update last scan
            self.last_card_id = card_id
            self.last_scan_time = datetime.now()

            logger.info(f"Card read: {card_id}")
            return card_id

        except Empty:
            # Timeout - no card scanned
            return None
        except Exception as e:
            logger.error(f"Unexpected error while reading card: {e}")
            return None

    def _process_card_data(self, card_data: str) -> str:
        """
        Process raw card data into card ID

        Args:
            card_data: Raw string from keyboard input

        Returns:
            Processed card ID string
        """
        try:
            # Strip whitespace
            card_str = card_data.strip()

            # Convert to uppercase if it looks like hex data
            if all(c in '0123456789ABCDEFabcdef \r\n\t' for c in card_str):
                card_str = card_str.replace(' ', '').upper()

            return card_str

        except Exception as e:
            logger.error(f"Error processing card data: {e}")
            return card_data

    def _is_duplicate_scan(self, card_id: str) -> bool:
        """
        Check if this is a duplicate scan of the same card

        Args:
            card_id: Card ID to check

        Returns:
            True if duplicate, False otherwise
        """
        if not self.last_card_id or not self.last_scan_time:
            return False

        # Same card ID
        if card_id != self.last_card_id:
            return False

        # Within duplicate window
        time_since_last = datetime.now() - self.last_scan_time
        if time_since_last < timedelta(seconds=Config.DUPLICATE_SCAN_WINDOW):
            return True

        return False

    def test_connection(self) -> bool:
        """
        Test if reader is still connected and responding

        For HID keyboards, always returns True if connected.

        Returns:
            True if connected, False otherwise
        """
        return self.is_connected

    def get_status(self) -> dict:
        """
        Get reader status information

        Returns:
            Dictionary with status information
        """
        return {
            "connected": self.is_connected,
            "port": self.port,
            "type": "HID Keyboard",
            "last_card_id": self.last_card_id,
            "last_scan_time": self.last_scan_time.isoformat() if self.last_scan_time else None
        }

    @staticmethod
    def list_available_ports():
        """
        List all available serial ports

        For HID keyboards, this returns a dummy entry.

        Returns:
            List with single entry for HID keyboard
        """
        return [("HID Keyboard", "RFID reader acting as keyboard input device")]

    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()

    def __del__(self):
        """Destructor"""
        self.disconnect()
