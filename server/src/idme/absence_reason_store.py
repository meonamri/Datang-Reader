"""
Absence Reason Store for IDME Module

Stores per-student absence reasons collected before the cutoff (e.g. via the
Telegram bot) in the `absence_reasons` table of idme_data.db. AbsenceDetector
reads these to override the default reason (MALAS KE SEKOLAH) for the students a
teacher gave a reason for; everyone else keeps the default.

Reasons are keyed by (scan_date, class_name, student_name) and upserted, so a
teacher can change a student's reason any time before the cutoff submits.
"""

import sqlite3
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, date
from pathlib import Path

from .migrations import apply_migrations
from .names import normalize_name
from .moeis_codes import SEBAB_TO_CATEGORY


class AbsenceReasonError(Exception):
    """Base exception for absence reason store errors."""
    pass


class AbsenceReasonStore:
    """Reads and writes per-student absence reasons in idme_data.db."""

    def __init__(self, db_path: str):
        """
        Initialize the store.

        Args:
            db_path: Path to idme_data.db SQLite database.
        """
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
        """Ensure the database and absence_reasons table exist."""
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

    def upsert_reason(
        self,
        class_name: str,
        student_name: str,
        sebab_id: str,
        scan_date: Optional[str] = None,
        idpelajar: Optional[str] = None,
        set_by: Optional[int] = None,
        source: str = 'telegram',
    ) -> Dict[str, Any]:
        """
        Record (or change) the absence reason for one student on one day.

        The category is derived from the sebab_id via SEBAB_TO_CATEGORY, so callers
        only supply the sebab code. Upserts on (scan_date, class_name,
        student_name) — recording a second reason for the same student replaces the
        first.

        Args:
            class_name: Class name (e.g. '5 UKM').
            student_name: Student name (stored uppercase, matches the roster name).
            sebab_id: MOEIS sebab code (e.g. 'D0010075').
            scan_date: YYYY-MM-DD (default: today).
            idpelajar: MOEIS portal student id, when known (preferred match key).
            set_by: teachers.id that recorded the reason (for the audit trail).
            source: where the reason came from (default 'telegram').

        Returns:
            The stored row as a dict.

        Raises:
            AbsenceReasonError: If sebab_id is not a known MOEIS code.
        """
        category = SEBAB_TO_CATEGORY.get(sebab_id)
        if not category:
            raise AbsenceReasonError(f"Unknown MOEIS sebab_id: {sebab_id!r}")

        if scan_date is None:
            scan_date = date.today().isoformat()
        name = student_name.strip().upper()
        now = datetime.now().isoformat()

        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO absence_reasons
                       (scan_date, class_name, student_name, idpelajar,
                        sebab_id, category, set_by, source, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(scan_date, class_name, student_name) DO UPDATE SET
                       idpelajar = excluded.idpelajar,
                       sebab_id  = excluded.sebab_id,
                       category  = excluded.category,
                       set_by    = excluded.set_by,
                       source    = excluded.source,
                       updated_at = excluded.updated_at""",
                (scan_date, class_name, name, idpelajar,
                 sebab_id, category, set_by, source, now),
            )
            conn.commit()
        except sqlite3.Error as e:
            raise AbsenceReasonError(f"Failed to store absence reason: {e}")
        finally:
            conn.close()

        self.logger.info(
            f"Recorded reason for {name} ({class_name}) on {scan_date}: "
            f"{sebab_id} (source={source})"
        )
        return {
            'scan_date': scan_date,
            'class_name': class_name,
            'student_name': name,
            'idpelajar': idpelajar,
            'sebab_id': sebab_id,
            'category': category,
            'set_by': set_by,
            'source': source,
        }

    def get_reasons_for(
        self,
        class_name: str,
        scan_date: Optional[str] = None,
    ) -> Dict[str, Dict[str, str]]:
        """
        Get all stored reasons for a class on a day, indexed for fast lookup by
        AbsenceDetector.

        Returns a dict whose keys are BOTH the idpelajar (when present) and the
        normalized student name, each mapping to {'sebab_id', 'category'}. A caller
        can therefore match a roster row by idpelajar first, then fall back to the
        normalized name, without a second query.

        Args:
            class_name: Class name.
            scan_date: YYYY-MM-DD (default: today).
        """
        if scan_date is None:
            scan_date = date.today().isoformat()

        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT student_name, idpelajar, sebab_id, category "
                "FROM absence_reasons WHERE scan_date = ? AND class_name = ?",
                (scan_date, class_name),
            ).fetchall()
        finally:
            conn.close()

        index: Dict[str, Dict[str, str]] = {}
        for row in rows:
            entry = {'sebab_id': row['sebab_id'], 'category': row['category']}
            if row['idpelajar']:
                index[f"id:{row['idpelajar']}"] = entry
            index[f"name:{normalize_name(row['student_name'])}"] = entry
        return index

    @staticmethod
    def id_key(idpelajar: str) -> str:
        """Lookup key for matching a roster row by idpelajar."""
        return f"id:{idpelajar}"

    @staticmethod
    def name_key(normalized_name: str) -> str:
        """Lookup key for matching a roster row by normalized name."""
        return f"name:{normalized_name}"
