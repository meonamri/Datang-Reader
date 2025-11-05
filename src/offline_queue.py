"""
Offline Queue Module

This module handles queuing of attendance records when network is unavailable
and automatic synchronization when connection is restored.
"""

import sqlite3
import logging
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from contextlib import contextmanager
from .config import Config
from .api_client import DatangAPIClient, NetworkError, AttendanceSubmissionError


logger = logging.getLogger(__name__)


class AttendanceQueue:
    """Manages offline attendance queue with SQLite"""

    def __init__(self, db_file: Optional[str] = None):
        """
        Initialize attendance queue

        Args:
            db_file: Path to SQLite database file. If None, use config default.
        """
        self.db_file = db_file or Config.DATABASE_FILE
        self._init_database()
        logger.info(f"Initialized attendance queue (database: {self.db_file})")

    def _init_database(self):
        """Initialize database schema"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Create attendance queue table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS attendance_queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        card_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        temperature REAL,
                        device_id TEXT NOT NULL,
                        queued_at TEXT NOT NULL,
                        retry_count INTEGER DEFAULT 0,
                        last_error TEXT,
                        status TEXT DEFAULT 'pending'
                    )
                ''')

                # Create index for efficient queries
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_status
                    ON attendance_queue(status)
                ''')

                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_timestamp
                    ON attendance_queue(timestamp)
                ''')

                conn.commit()
                logger.debug("Database initialized")

        except sqlite3.Error as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    @contextmanager
    def _get_connection(self):
        """Get database connection with context manager"""
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        try:
            yield conn
        finally:
            conn.close()

    def enqueue(
        self,
        card_id: str,
        timestamp: datetime,
        temperature: Optional[float] = None,
        device_id: Optional[str] = None
    ) -> int:
        """
        Add attendance record to queue

        Args:
            card_id: RFID card ID
            timestamp: Attendance timestamp
            temperature: Optional temperature reading
            device_id: Device ID (defaults to config)

        Returns:
            Queue entry ID
        """
        device_id = device_id or Config.DEVICE_ID

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    INSERT INTO attendance_queue
                    (card_id, timestamp, temperature, device_id, queued_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    card_id,
                    timestamp.isoformat(),
                    temperature,
                    device_id,
                    datetime.now().isoformat()
                ))

                conn.commit()
                entry_id = cursor.lastrowid

                logger.info(f"Queued attendance record (ID: {entry_id}, card: {card_id[:8]}...)")
                return entry_id

        except sqlite3.Error as e:
            logger.error(f"Failed to enqueue attendance: {e}")
            raise

    def get_pending(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get pending attendance records

        Args:
            limit: Maximum number of records to retrieve

        Returns:
            List of pending attendance records
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                query = '''
                    SELECT * FROM attendance_queue
                    WHERE status = 'pending'
                    AND retry_count < ?
                    ORDER BY timestamp ASC
                '''

                if limit:
                    query += f' LIMIT {limit}'

                cursor.execute(query, (Config.MAX_RETRY_ATTEMPTS,))
                rows = cursor.fetchall()

                return [dict(row) for row in rows]

        except sqlite3.Error as e:
            logger.error(f"Failed to get pending records: {e}")
            return []

    def mark_synced(self, entry_id: int):
        """
        Mark attendance record as successfully synced

        Args:
            entry_id: Queue entry ID
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    UPDATE attendance_queue
                    SET status = 'synced'
                    WHERE id = ?
                ''', (entry_id,))

                conn.commit()
                logger.info(f"Marked record {entry_id} as synced")

        except sqlite3.Error as e:
            logger.error(f"Failed to mark record as synced: {e}")

    def mark_failed(self, entry_id: int, error_message: str):
        """
        Mark attendance record as failed with error

        Args:
            entry_id: Queue entry ID
            error_message: Error description
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    UPDATE attendance_queue
                    SET retry_count = retry_count + 1,
                        last_error = ?
                    WHERE id = ?
                ''', (error_message, entry_id))

                # Check if max retries exceeded
                cursor.execute('''
                    UPDATE attendance_queue
                    SET status = 'failed'
                    WHERE id = ? AND retry_count >= ?
                ''', (entry_id, Config.MAX_RETRY_ATTEMPTS))

                conn.commit()
                logger.warning(f"Marked record {entry_id} as failed: {error_message}")

        except sqlite3.Error as e:
            logger.error(f"Failed to mark record as failed: {e}")

    def sync_with_api(self, api_client: DatangAPIClient) -> Dict[str, int]:
        """
        Synchronize pending records with API

        Args:
            api_client: Authenticated API client

        Returns:
            Dictionary with sync statistics
        """
        logger.info("Starting queue synchronization...")

        stats = {
            "total": 0,
            "synced": 0,
            "failed": 0,
            "skipped": 0
        }

        # Get pending records
        pending = self.get_pending(limit=100)  # Process in batches
        stats["total"] = len(pending)

        if not pending:
            logger.info("No pending records to sync")
            return stats

        logger.info(f"Found {len(pending)} pending records")

        for record in pending:
            entry_id = record["id"]
            card_id = record["card_id"]
            timestamp = datetime.fromisoformat(record["timestamp"])
            temperature = record.get("temperature")

            try:
                # Submit to API
                response = api_client.submit_attendance(
                    card_id=card_id,
                    timestamp=timestamp,
                    temperature=temperature
                )

                # Mark as synced
                self.mark_synced(entry_id)
                stats["synced"] += 1

                logger.info(f"Synced record {entry_id} (card: {card_id[:8]}...)")

            except NetworkError as e:
                logger.warning(f"Network error syncing record {entry_id}: {e}")
                stats["skipped"] += 1
                # Stop syncing on network error
                break

            except AttendanceSubmissionError as e:
                logger.error(f"Failed to sync record {entry_id}: {e}")
                self.mark_failed(entry_id, str(e))
                stats["failed"] += 1

            except Exception as e:
                logger.error(f"Unexpected error syncing record {entry_id}: {e}")
                self.mark_failed(entry_id, f"Unexpected error: {e}")
                stats["failed"] += 1

        logger.info(f"Sync complete: {stats['synced']} synced, {stats['failed']} failed, "
                   f"{stats['skipped']} skipped")
        return stats

    def get_queue_size(self) -> int:
        """
        Get number of pending records in queue

        Returns:
            Number of pending records
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) FROM attendance_queue
                    WHERE status = 'pending'
                ''')
                return cursor.fetchone()[0]

        except sqlite3.Error as e:
            logger.error(f"Failed to get queue size: {e}")
            return 0

    def get_failed_count(self) -> int:
        """
        Get number of permanently failed records

        Returns:
            Number of failed records
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) FROM attendance_queue
                    WHERE status = 'failed'
                ''')
                return cursor.fetchone()[0]

        except sqlite3.Error as e:
            logger.error(f"Failed to get failed count: {e}")
            return 0

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get queue statistics

        Returns:
            Dictionary with queue statistics
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Get counts by status
                cursor.execute('''
                    SELECT status, COUNT(*) as count
                    FROM attendance_queue
                    GROUP BY status
                ''')
                status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}

                # Get oldest pending
                cursor.execute('''
                    SELECT MIN(timestamp) as oldest
                    FROM attendance_queue
                    WHERE status = 'pending'
                ''')
                oldest_pending = cursor.fetchone()["oldest"]

                return {
                    "pending": status_counts.get("pending", 0),
                    "synced": status_counts.get("synced", 0),
                    "failed": status_counts.get("failed", 0),
                    "oldest_pending": oldest_pending,
                    "total": sum(status_counts.values())
                }

        except sqlite3.Error as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}

    def cleanup_old_records(self, days: int = 30):
        """
        Clean up old synced records

        Args:
            days: Delete synced records older than this many days
        """
        try:
            cutoff_date = datetime.now().timestamp() - (days * 24 * 60 * 60)
            cutoff_str = datetime.fromtimestamp(cutoff_date).isoformat()

            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    DELETE FROM attendance_queue
                    WHERE status = 'synced'
                    AND timestamp < ?
                ''', (cutoff_str,))

                deleted = cursor.rowcount
                conn.commit()

                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} old synced records")

        except sqlite3.Error as e:
            logger.error(f"Failed to cleanup old records: {e}")

    def clear_all(self):
        """Clear all records from queue (use with caution!)"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM attendance_queue')
                conn.commit()
                logger.warning("Cleared all records from queue")

        except sqlite3.Error as e:
            logger.error(f"Failed to clear queue: {e}")
