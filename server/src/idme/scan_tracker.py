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

            recorded = cursor.rowcount > 0
            if recorded:
                self.logger.debug(
                    f"Recorded scan: {student_name} ({class_name}) at {scan_time}"
                )
            else:
                self.logger.debug(
                    f"Duplicate scan ignored: {student_name} ({class_name})"
                )
        except sqlite3.Error as e:
            self.logger.error(f"Failed to record scan: {e}")
            return False
        finally:
            conn.close()

        # Passive tag learning (best-effort; runs even on a duplicate daily scan
        # so a same-day card replacement is still picked up). Never raises — tag
        # learning must not break the proven scan-recording path.
        try:
            self._learn_tag(card_id, student_name, class_name, today)
        except Exception as e:
            self.logger.warning(f"Tag learning failed (non-critical): {e}")

        return recorded

    def _learn_tag(
        self, card_id: str, scan_name: str, scan_class: str, scan_date: str
    ) -> None:
        """
        Attach the scanned RFID tag to the matching registry student
        (IDENTITY_RESOLUTION_DESIGN.md §5.2). Resolution is by normalized
        (name, class):

        - exactly one match -> set integration_tag (if NULL or changed),
          tag_source='learned', tag_updated_at=now. (A changed card_id is a card
          replacement; the old tag is simply overwritten.)
        - no match          -> record an 'no_match' unmatched_scan (deduped/day).
        - multiple matches  -> AMBIGUOUS (duplicate names): do NOT auto-attach;
          record an 'ambiguous' unmatched_scan so an admin can resolve it. RFID
          tags disambiguate the twins from then on.
        """
        from .names import normalize_name

        if not card_id or not scan_class:
            return
        key = normalize_name(scan_name)

        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT id, name, integration_tag FROM students "
                "WHERE class_name = ? AND enabled = 1",
                (scan_class,)
            ).fetchall()
            matches = [r for r in rows if normalize_name(r['name']) == key]

            if len(matches) == 1:
                m = matches[0]
                if m['integration_tag'] != card_id:  # NULL or replaced card
                    conn.execute(
                        "UPDATE students SET integration_tag = ?, "
                        "tag_source = 'learned', tag_updated_at = ? WHERE id = ?",
                        (card_id, datetime.now().isoformat(), m['id'])
                    )
                    conn.commit()
                    action = "learned" if m['integration_tag'] is None else "updated"
                    self.logger.info(
                        f"Tag {action} for student id={m['id']} in '{scan_class}'"
                    )
            elif not matches:
                self._record_unmatched(
                    conn, card_id, scan_name, scan_class, scan_date, 'no_match'
                )
            else:
                self._record_unmatched(
                    conn, card_id, scan_name, scan_class, scan_date, 'ambiguous'
                )
        finally:
            conn.close()

    def _record_unmatched(
        self, conn, card_id, scan_name, scan_class, scan_date, reason
    ) -> None:
        """Insert an unmatched_scans alert row (deduped per card_id+date)."""
        conn.execute(
            "INSERT OR IGNORE INTO unmatched_scans "
            "(card_id, scan_name, scan_class, scan_date, reason) "
            "VALUES (?, ?, ?, ?, ?)",
            (card_id, scan_name, scan_class, scan_date, reason)
        )
        conn.commit()
        self.logger.warning(
            f"Unmatched scan ({reason}) in '{scan_class}': card={card_id} "
            f"matched no single registry student"
        )

    def get_scanned_tags(
        self, class_name: str, scan_date: Optional[str] = None
    ) -> set:
        """
        Get the set of RFID tags (integration_tag) that scanned for a class on a
        date. This is the name-free key for tag-first absence detection.
        """
        if scan_date is None:
            scan_date = date.today().isoformat()
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT DISTINCT integration_tag FROM daily_scans "
                "WHERE class_name = ? AND scan_date = ? "
                "AND integration_tag IS NOT NULL",
                (class_name, scan_date)
            ).fetchall()
            return {r['integration_tag'] for r in rows}
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

    def get_unmatched_summary(self) -> Dict[str, Any]:
        """
        Counts of pending (unresolved) unmatched scans for the coverage panel:
        scans that matched no registry student ('no_match') and duplicate-name
        first-taps that couldn't be auto-attached ('ambiguous').
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT reason, COUNT(*) AS c FROM unmatched_scans "
                "WHERE resolved = 0 GROUP BY reason"
            ).fetchall()
        finally:
            conn.close()
        counts = {(r['reason'] or 'unknown'): r['c'] for r in rows}
        return {
            'no_match': counts.get('no_match', 0),
            'ambiguous': counts.get('ambiguous', 0),
            'total': sum(counts.values()),
        }

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
