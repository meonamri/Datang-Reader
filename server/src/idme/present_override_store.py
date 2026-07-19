"""
Present-Override Store for IDME Module

Records per-student "Hadir (lupa kad)" overrides collected via the Telegram bot:
a teacher asserts an absentee is actually present but forgot their RFID card. Two
consumers read these rows:

  * AbsenceDetector — DROPS an overridden student from the day's absent list (so
    they are never submitted absent to MOEIS) and counts them as present in the
    attendance summary, keeping roster = present + absent.
  * The over-limit admin alert — mark_present returns the student's distinct
    Hadir days in the trailing window so the bot can flag a repeat offender.

Overrides are keyed by (scan_date, class_name, student_name) and upserted, so a
repeat tap on the same day stays one row. A present-override and an absence reason
are mutually exclusive for a student on a day; the bot clears the other store when
one is set, and clear_override() here backs the "undo Hadir" button.
"""

import sqlite3
import logging
from typing import Dict, Optional, Any
from datetime import datetime, date, timedelta
from pathlib import Path

from .migrations import apply_migrations
from .names import normalize_name


class PresentOverrideError(Exception):
    """Base exception for present-override store errors."""
    pass


class PresentOverrideStore:
    """Reads and writes per-student present-overrides in idme_data.db."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.logger = logging.getLogger(__name__)
        self._ensure_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection with WAL mode for concurrent access."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_db(self):
        """Ensure the database and present_overrides table exist."""
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

    def mark_present(
        self,
        class_name: str,
        student_name: str,
        scan_date: Optional[str] = None,
        idpelajar: Optional[str] = None,
        set_by: Optional[int] = None,
        source: str = 'telegram',
        window_days: int = 14,
    ) -> Dict[str, Any]:
        """
        Record (or refresh) a "Hadir (lupa kad)" override for one student on one
        day, and return the student's distinct Hadir-day count in the trailing
        ``window_days`` (INCLUDING this day) so the caller can alert on a
        threshold breach.

        Upserts on (scan_date, class_name, student_name), so a repeat tap the same
        day never inflates the window count.

        Returns:
            {'scan_date', 'class_name', 'student_name', 'idpelajar', 'set_by',
             'source', 'window_count'}.
        """
        if scan_date is None:
            scan_date = date.today().isoformat()
        name = student_name.strip().upper()
        now = datetime.now().isoformat()

        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO present_overrides
                       (scan_date, class_name, student_name, idpelajar,
                        set_by, source, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(scan_date, class_name, student_name) DO UPDATE SET
                       idpelajar  = excluded.idpelajar,
                       set_by     = excluded.set_by,
                       source     = excluded.source,
                       updated_at = excluded.updated_at""",
                (scan_date, class_name, name, idpelajar, set_by, source, now),
            )
            conn.commit()
            window_count = self._count_in_window(
                conn, class_name, name, idpelajar, scan_date, window_days
            )
        except sqlite3.Error as e:
            raise PresentOverrideError(f"Failed to store present override: {e}")
        finally:
            conn.close()

        self.logger.info(
            f"Recorded Hadir override for {name} ({class_name}) on {scan_date}: "
            f"{window_count} day(s) in the last {window_days} (source={source})"
        )
        return {
            'scan_date': scan_date,
            'class_name': class_name,
            'student_name': name,
            'idpelajar': idpelajar,
            'set_by': set_by,
            'source': source,
            'window_count': window_count,
        }

    def clear_override(
        self,
        class_name: str,
        student_name: str,
        scan_date: Optional[str] = None,
    ) -> bool:
        """Remove a student's present-override for a day (backs the "undo Hadir"
        button, and is called when a reason is set instead). Returns True if a row
        was deleted."""
        if scan_date is None:
            scan_date = date.today().isoformat()
        name = student_name.strip().upper()
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "DELETE FROM present_overrides "
                "WHERE scan_date = ? AND class_name = ? AND student_name = ?",
                (scan_date, class_name, name),
            )
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.Error as e:
            raise PresentOverrideError(f"Failed to clear present override: {e}")
        finally:
            conn.close()

    def get_overrides_for(
        self,
        class_name: str,
        scan_date: Optional[str] = None,
    ) -> Dict[str, bool]:
        """
        Get all present-overrides for a class on a day, indexed for the same
        idpelajar-then-name lookup AbsenceDetector uses for reasons.

        Returns a dict whose keys are BOTH ``id:<idpelajar>`` (when present) and
        ``name:<normalized_name>``, each mapping to True. A caller matches a roster
        row by idpelajar first, then normalized name, without a second query.
        """
        if scan_date is None:
            scan_date = date.today().isoformat()

        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT student_name, idpelajar FROM present_overrides "
                "WHERE scan_date = ? AND class_name = ?",
                (scan_date, class_name),
            ).fetchall()
        finally:
            conn.close()

        index: Dict[str, bool] = {}
        for row in rows:
            if row['idpelajar']:
                index[self.id_key(row['idpelajar'])] = True
            index[self.name_key(normalize_name(row['student_name']))] = True
        return index

    @staticmethod
    def _count_in_window(
        conn: sqlite3.Connection,
        class_name: str,
        name: str,
        idpelajar: Optional[str],
        scan_date: str,
        window_days: int,
    ) -> int:
        """Distinct Hadir days for one student in the trailing ``window_days``
        ending on (and including) ``scan_date``. Matches on class + uppercase name,
        OR on idpelajar when known, so a card replacement that changes nothing but
        the tag still counts against the same student."""
        try:
            end = date.fromisoformat(scan_date)
        except ValueError:
            end = date.today()
        start = (end - timedelta(days=max(0, window_days - 1))).isoformat()
        row = conn.execute(
            "SELECT COUNT(DISTINCT scan_date) AS n FROM present_overrides "
            "WHERE class_name = ? AND scan_date BETWEEN ? AND ? "
            "AND (student_name = ? OR (idpelajar IS NOT NULL AND idpelajar = ?))",
            (class_name, start, scan_date, name, idpelajar),
        ).fetchone()
        return int(row['n']) if row else 0

    def count_in_window(
        self,
        class_name: str,
        student_name: str,
        scan_date: Optional[str] = None,
        idpelajar: Optional[str] = None,
        window_days: int = 14,
    ) -> int:
        """Public wrapper over :meth:`_count_in_window` (opens its own connection)."""
        if scan_date is None:
            scan_date = date.today().isoformat()
        name = student_name.strip().upper()
        conn = self._get_conn()
        try:
            return self._count_in_window(
                conn, class_name, name, idpelajar, scan_date, window_days
            )
        finally:
            conn.close()

    @staticmethod
    def id_key(idpelajar: str) -> str:
        """Lookup key for matching a roster row by idpelajar."""
        return f"id:{idpelajar}"

    @staticmethod
    def name_key(normalized_name: str) -> str:
        """Lookup key for matching a roster row by normalized name."""
        return f"name:{normalized_name}"
