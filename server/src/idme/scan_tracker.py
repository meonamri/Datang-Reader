"""
Scan Tracker for IDME Module

Records RFID scans from Datang API responses into idme_data.db.
Called after each successful Datang API scan to track who is present.
Used by AbsenceDetector to determine who is absent.
"""

import sqlite3
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, date
from pathlib import Path

from .migrations import apply_migrations


class ScanTrackerError(Exception):
    """Base exception for scan tracker errors."""
    pass


class ScanTracker:
    """
    Records and queries RFID scans for absence detection.

    Each scan is stored with student_name, class_name, and scan_date.
    Duplicate scans (same student + same date) are ignored via UPSERT.
    """

    def __init__(self, db_path: str):
        """
        Initialize scan tracker.

        Args:
            db_path: Path to idme_data.db SQLite database.
        """
        self.db_path = Path(db_path)
        self.logger = logging.getLogger(__name__)
        self._ensure_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_db(self):
        """Ensure the database and daily_scans table exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = self._get_conn()
        try:
            schema_path = Path(__file__).parent / 'schema.sql'
            if schema_path.exists():
                conn.executescript(schema_path.read_text())
            conn.commit()
            apply_migrations(conn)
        finally:
            conn.close()

    def record_scan(self, card_id: str, datang_response: Dict[str, Any]) -> bool:
        """
        Record a successful scan from Datang API response.

        Called from ServiceManager.process_attendance() after successful API call.
        Extracts name, section (class), and time from the response.
        Uses INSERT OR IGNORE to avoid duplicates (same student + same date).

        Args:
            card_id: RFID card ID (integration_tag).
            datang_response: The 'data' dict from Datang API response:
                {
                    'name': 'STUDENT NAME',
                    'section': '5 UKM',
                    'time_text': '14:30:45 01 January 2024',
                    'pid': 'person_id',
                    ...
                }

        Returns:
            True if recorded (new scan), False if duplicate.
        """
        if not datang_response or not isinstance(datang_response, dict):
            self.logger.warning("Invalid Datang response, skipping scan recording")
            return False

        student_name = datang_response.get('name', '').strip().upper()
        class_name = datang_response.get('section', '').strip()
        datang_pid = datang_response.get('pid', '')
        time_text = datang_response.get('time_text', '')

        if not student_name or not class_name:
            self.logger.warning(
                f"Missing name or section in Datang response for card {card_id}"
            )
            return False

        today = date.today().isoformat()
        scan_time = datetime.now().isoformat()

        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO daily_scans
                   (student_name, class_name, integration_tag, scan_time, scan_date, datang_pid)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (student_name, class_name, card_id, scan_time, today, datang_pid)
            )
            conn.commit()

            if cursor.rowcount > 0:
                self.logger.debug(
                    f"Recorded scan: {student_name} ({class_name}) at {scan_time}"
                )
                return True
            else:
                self.logger.debug(
                    f"Duplicate scan ignored: {student_name} ({class_name})"
                )
                return False

        except sqlite3.Error as e:
            self.logger.error(f"Failed to record scan: {e}")
            return False
        finally:
            conn.close()

    def get_scanned_students(
        self,
        class_name: str,
        scan_date: Optional[str] = None
    ) -> List[str]:
        """
        Get names of students who scanned today for a given class.

        Args:
            class_name: Class name (e.g., '5 UKM').
            scan_date: Date in YYYY-MM-DD format (default: today).

        Returns:
            List of student names (uppercase).
        """
        if scan_date is None:
            scan_date = date.today().isoformat()

        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT student_name FROM daily_scans "
                "WHERE class_name = ? AND scan_date = ? "
                "ORDER BY student_name",
                (class_name, scan_date)
            ).fetchall()
            return [row['student_name'] for row in rows]
        finally:
            conn.close()

    def get_scan_count(
        self,
        class_name: str,
        scan_date: Optional[str] = None
    ) -> int:
        """
        Get count of scans for a class today.

        Args:
            class_name: Class name.
            scan_date: Date in YYYY-MM-DD (default: today).

        Returns:
            Number of unique students who scanned.
        """
        if scan_date is None:
            scan_date = date.today().isoformat()

        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM daily_scans "
                "WHERE class_name = ? AND scan_date = ?",
                (class_name, scan_date)
            ).fetchone()
            return row['cnt']
        finally:
            conn.close()

    def get_all_scans_today(self) -> Dict[str, int]:
        """
        Get scan counts per class for today.

        Returns:
            Dict: {'5 UKM': 22, '4 UM': 18, ...}
        """
        today = date.today().isoformat()

        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT class_name, COUNT(*) as cnt "
                "FROM daily_scans WHERE scan_date = ? "
                "GROUP BY class_name ORDER BY class_name",
                (today,)
            ).fetchall()
            return {row['class_name']: row['cnt'] for row in rows}
        finally:
            conn.close()

    def cleanup_old_scans(self, days: int = 30) -> int:
        """
        Remove scans older than N days.

        Args:
            days: Number of days to keep (default: 30).

        Returns:
            Number of records deleted.
        """
        from datetime import timedelta

        cutoff = (date.today() - timedelta(days=days)).isoformat()

        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM daily_scans WHERE scan_date < ?",
                (cutoff,)
            )
            conn.commit()
            count = cursor.rowcount
            if count > 0:
                self.logger.info(f"Cleaned up {count} scans older than {days} days")
            return count
        finally:
            conn.close()
