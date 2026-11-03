"""
Service Manager Module

Main service orchestrator that coordinates all components.
"""

import logging
import os
import time
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from .config import Config
from .rfid_reader import RFIDReader
from .api_client import DatangAPIClient, MockAPIClient, NetworkError, AuthenticationError, AttendanceSubmissionError
from .auth_manager import AuthManager
from .offline_queue import AttendanceQueue
from .local_attendance import LocalAttendanceStore, DatangMirror, mode_from_env


logger = logging.getLogger(__name__)


class ServiceManager:
    """Main service manager coordinating all components"""

    def __init__(self, use_mock_api: bool = False):
        """
        Initialize service manager

        Args:
            use_mock_api: Use mock API client for testing
        """
        self.use_mock_api = use_mock_api
        self.running = False

        # Initialize components
        logger.info("Initializing Datang Reader service...")

        # RFID Reader
        self.rfid_reader = RFIDReader()

        # API Client
        if use_mock_api:
            logger.warning("Using MOCK API client - for development only!")
            self.api_client = MockAPIClient()
        else:
            self.api_client = DatangAPIClient()

        # Authentication Manager
        self.auth_manager = AuthManager(self.api_client)

        # Offline Queue
        self.queue = AttendanceQueue()

        # IDME scan tracker (set by init_idme_module if IDME is enabled)
        self.scan_tracker = None

        # Local attendance authority (see local_attendance.py). 'datang' = the
        # historical behaviour, nothing below is constructed.
        self.attendance_mode = mode_from_env()
        self.local_attendance: Optional[LocalAttendanceStore] = None
        self.datang_mirror: Optional[DatangMirror] = None
        if self.attendance_mode != "datang":
            db_path = os.getenv("ATTENDANCE_DB_PATH") or os.getenv(
                "IDME_DATABASE_PATH", "/data/idme/idme_data.db")
            try:
                self.local_attendance = LocalAttendanceStore(db_path, mode=self.attendance_mode)
                self.local_attendance.seed_from_history()
            except Exception as e:
                # Never let the new path take attendance down: fall back to Datang.my.
                logger.error(f"Local attendance unavailable ({e}); falling back to ATTENDANCE_MODE=datang")
                self.attendance_mode = "datang"
                self.local_attendance = None
        self.mirror_enabled = (
            self.attendance_mode == "local"
            and os.getenv("ATTENDANCE_DATANG_MIRROR", "true").strip().lower() in ("1", "true", "yes")
        )
        logger.info(f"Attendance authority: {self.attendance_mode}"
                    + (" (mirroring to Datang.my)" if self.mirror_enabled else ""))

        logger.info("Service manager initialized")

    def start(self) -> bool:
        """
        Start the service

        Returns:
            True if started successfully, False otherwise
        """
        logger.info("Starting Datang Reader service...")

        # Validate configuration
        is_valid, errors = Config.validate()
        if not is_valid:
            logger.error("Configuration validation failed:")
            for error in errors:
                logger.error(f"  - {error}")
            return False

        # Connect RFID reader
        logger.info("Connecting to RFID reader...")
        if not self.rfid_reader.connect():
            logger.error("Failed to connect to RFID reader")
            return False

        logger.info("RFID reader connected")

        if self.attendance_mode == "local":
            # Datang.my is optional here: a login failure must not stop taps
            # being recorded, and the legacy offline queue is NOT replayed at
            # startup (replays are uncertain writes; use POST /sync by hand).
            if self.mirror_enabled:
                if not self.auth_manager.ensure_authenticated():
                    logger.warning("Datang.my login failed; mirror will keep retrying")
                self.datang_mirror = DatangMirror(self.local_attendance, self.api_client, self.auth_manager)
                self.datang_mirror.start()
            self.running = True
            logger.info("Service started (local attendance authority)")
            return True

        # Authenticate with API
        logger.info("Authenticating with Datang API...")
        if not self.auth_manager.ensure_authenticated():
            logger.error("Failed to authenticate with API")
            logger.error("Please check READER_USERNAME and READER_PASSWORD in configuration")
            return False

        logger.info("API authentication successful")

        # Try initial sync
        logger.info("Performing initial queue sync...")
        self.sync_queue()

        self.running = True
        logger.info("Service started successfully")
        return True

    def stop(self):
        """Stop the service"""
        logger.info("Stopping Datang Reader service...")
        self.running = False

        if self.datang_mirror:
            self.datang_mirror.stop()

        # Disconnect RFID reader
        if self.rfid_reader:
            self.rfid_reader.disconnect()

        logger.info("Service stopped")

    def _record_idme_scan(
        self, card_id: str, response: Any, scanned_at: Optional[datetime] = None
    ) -> None:
        """
        Record a successful scan into the IDME scan tracker (if enabled).

        api_client.submit_attendance() returns the unwrapped student dict
        ({name, section, pid, ...}) on success, so the response IS the data
        dict that record_scan expects — pass it directly. Best-effort: never
        raise, so IDME tracking can't break the proven attendance path.
        """
        if self.scan_tracker and isinstance(response, dict) and response.get("name"):
            try:
                self.scan_tracker.record_scan(card_id, response, scanned_at=scanned_at)
            except Exception as scan_err:
                logger.warning(f"IDME scan recording failed (non-critical): {scan_err}")

    def process_attendance(
        self,
        card_id: str,
        temperature: Optional[float] = None,
        scanned_at: Optional[datetime] = None,
        reader_id: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process attendance for a scanned card, routed by ATTENDANCE_MODE.

        Args:
            card_id: RFID card ID
            temperature: Optional temperature reading
            scanned_at: Original tap time from a reader outbox (local mode only;
                Datang.my cannot accept one)
            reader_id: Reader identity, for the audit log
            event_id: Client event id; makes a resent tap idempotent (local mode)

        Returns:
            Dictionary with result information
        """
        if self.attendance_mode == "local":
            try:
                result = self.local_attendance.record(
                    card_id, scanned_at=scanned_at, reader_id=reader_id,
                    event_id=event_id, mirror=self.mirror_enabled)
                logger.info(f"Local attendance: card {card_id[:8]}... -> {result.get('status')}")
                return result
            except Exception as e:
                logger.error(f"Local attendance write failed ({e}); using Datang.my for this tap")

        # Datang.my stamps its own arrival time, but the IDME daily_scans row
        # must carry the real tap date, so a reader's delayed resend keeps it.
        timestamp = datetime.now()
        if scanned_at is not None:
            if timestamp - timedelta(days=7) <= scanned_at <= timestamp + timedelta(minutes=2):
                timestamp = scanned_at
            else:
                logger.warning(f"Ignoring implausible scanned_at {scanned_at.isoformat()} "
                               f"from reader {reader_id or '?'}")
        result = self._process_via_datang(card_id, temperature, timestamp)

        if self.attendance_mode == "shadow":
            try:
                self.local_attendance.record_shadow(card_id, timestamp, reader_id, result)
            except Exception as e:
                logger.warning(f"Shadow attendance logging failed (non-critical): {e}")
        return result

    def _process_via_datang(
        self, card_id: str, temperature: Optional[float], timestamp: datetime
    ) -> Dict[str, Any]:
        """The original Datang.my-authoritative path (unchanged behaviour)."""
        logger.info(f"Processing attendance for card: {card_id[:8]}...")

        try:
            # Try to submit directly to API
            response = self.api_client.submit_attendance(
                card_id=card_id,
                timestamp=timestamp,
                temperature=temperature
            )

            logger.info("Attendance submitted successfully")

            # Record scan for IDME absence detection (if enabled)
            self._record_idme_scan(card_id, response, scanned_at=timestamp)

            return {
                "success": True,
                "online": True,
                "message": response.get("message", "Attendance recorded!"),
                "data": response
            }

        except AuthenticationError as e:
            # Token expired, try to re-authenticate
            logger.warning(f"Authentication error, attempting re-login: {e}")

            if self.auth_manager.ensure_authenticated(force_login=True):
                # Retry submission
                try:
                    response = self.api_client.submit_attendance(
                        card_id=card_id,
                        timestamp=timestamp,
                        temperature=temperature
                    )
                    # Record scan for IDME absence detection (if enabled)
                    self._record_idme_scan(card_id, response, scanned_at=timestamp)
                    return {
                        "success": True,
                        "online": True,
                        "message": "Attendance recorded!",
                        "data": response
                    }
                except AttendanceSubmissionError as retry_error:
                    # API validation error on retry - don't queue
                    logger.error(f"Retry rejected by API: {retry_error}")
                    return {
                        "success": False,
                        "online": True,
                        "message": str(retry_error)
                    }
                except NetworkError as retry_error:
                    # Network error on retry - queue it
                    logger.error(f"Network error on retry: {retry_error}")
                    # Fall through to queue
                except Exception as retry_error:
                    logger.error(f"Retry failed: {retry_error}")
                    # Fall through to queue for other errors

            # Queue the record (only reached if re-auth failed or retry had network error)
            logger.info("Queueing attendance for later sync")
            entry_id = self.queue.enqueue(card_id, timestamp, temperature)

            return {
                "success": True,
                "online": False,
                "queued": True,
                "queue_id": entry_id,
                "message": "Recorded offline (will sync later)"
            }

        except NetworkError as e:
            # Network unavailable, queue the record
            logger.warning(f"Network error, queueing attendance: {e}")
            entry_id = self.queue.enqueue(card_id, timestamp, temperature)

            return {
                "success": True,
                "online": False,
                "queued": True,
                "queue_id": entry_id,
                "message": "Recorded offline (will sync later)"
            }

        except AttendanceSubmissionError as e:
            # API validation error (e.g., card not found) - don't queue, return error
            logger.error(f"Attendance submission rejected: {e}")
            return {
                "success": False,
                "online": True,
                "message": str(e)
            }

        except Exception as e:
            # Unexpected error
            logger.error(f"Unexpected error processing attendance: {e}")

            # Try to queue it anyway
            try:
                entry_id = self.queue.enqueue(card_id, timestamp, temperature)
                return {
                    "success": True,
                    "online": False,
                    "queued": True,
                    "queue_id": entry_id,
                    "message": f"Recorded offline due to error: {str(e)}"
                }
            except Exception as queue_error:
                logger.error(f"Failed to queue attendance: {queue_error}")
                return {
                    "success": False,
                    "message": f"Failed to record: {str(e)}"
                }

    def sync_queue(self) -> Dict[str, int]:
        """
        Synchronize offline queue with API

        Returns:
            Dictionary with sync statistics
        """
        # Ensure authenticated
        if not self.api_client.token:
            if not self.auth_manager.ensure_authenticated():
                logger.warning("Cannot sync queue: not authenticated")
                return {"total": 0, "synced": 0, "failed": 0, "skipped": 0}

        # Perform sync (feed synced offline scans into the IDME tracker too)
        stats = self.queue.sync_with_api(self.api_client, on_synced=self._record_idme_scan)

        # Cleanup old records periodically
        self.queue.cleanup_old_records(days=30)

        return stats

    def run_console_mode(self):
        """
        Run service in console mode (no GUI)

        This is a simple console-based interface for testing or headless operation.
        Uses keyboard input to capture HID RFID reader scans.
        """
        logger.info("Running in console mode...")
        print("\n" + "="*60)
        print("Datang Reader - Console Mode (HID Keyboard)")
        print("="*60)
        print("Scan RFID cards (they will type the card ID automatically)")
        print("Press Ctrl+C to quit\n")

        if not self.start():
            print("Failed to start service. Check logs for details.")
            return

        print("Service started. Ready for card scans...\n")
        print("Waiting for card scan (or type card ID manually for testing):")

        try:
            while self.running:
                # Wait for keyboard input (HID reader types card ID + Enter)
                try:
                    card_id = input().strip()

                    if card_id:
                        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Card scanned: {card_id}")

                        # Process attendance
                        result = self.process_attendance(card_id)

                        if result["success"]:
                            status = "ONLINE" if result.get("online") else "OFFLINE"
                            print(f"Success {status}: {result['message']}")
                        else:
                            print(f"Error: {result['message']}")

                        # Show queue status
                        queue_size = self.queue.get_queue_size()
                        if queue_size > 0:
                            print(f"Queue: {queue_size} pending records")

                        print("\nReady for next scan:")

                except EOFError:
                    # EOF reached (Ctrl+D on Unix, Ctrl+Z on Windows)
                    break

        except KeyboardInterrupt:
            print("\n\nShutting down...")
        finally:
            self.stop()

    def get_status(self) -> Dict[str, Any]:
        """
        Get comprehensive service status

        Returns:
            Dictionary with service status
        """
        return {
            "running": self.running,
            "rfid_reader": self.rfid_reader.get_status(),
            "api": self.api_client.get_status(),
            "queue": self.queue.get_statistics(),
            "device_id": Config.DEVICE_ID,
            "attendance": self.attendance_status(),
        }

    def attendance_status(self) -> Dict[str, Any]:
        if not self.local_attendance:
            return {"mode": self.attendance_mode}
        try:
            return {**self.local_attendance.stats(), "mirror_enabled": self.mirror_enabled}
        except Exception as e:
            return {"mode": self.attendance_mode, "error": str(e)}

    def health_check(self) -> bool:
        """
        Perform health check

        Returns:
            True if service is healthy, False otherwise
        """
        if not self.running:
            return False

        # Check RFID reader
        if not self.rfid_reader.test_connection():
            logger.warning("Health check: RFID reader not connected")
            return False

        # Local authority does not depend on Datang.my being logged in
        if self.attendance_mode == "local":
            return True

        # Check API authentication
        if not self.api_client.token:
            logger.warning("Health check: Not authenticated")
            return False

        return True
