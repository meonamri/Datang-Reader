"""
Session Cache for IDME Module

Caches IDME cookies and CSRF tokens per teacher to avoid re-login.
Sessions expire after 6 hours (configurable).

Ported from: idme-attendance-automation/automation/session_manager.py
Simplified: Uses idme_data.db, removed school.db dependency.
"""

import sqlite3
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path


class SessionCacheError(Exception):
    """Base exception for session cache errors."""
    pass


class SessionCache:
    """
    Manages IDME session caching for teachers.

    Stores cookies and CSRF tokens extracted during the 6-step login.
    Sessions are teacher-specific and expire after a configurable period.
    """

    def __init__(self, db_path: str):
        """
        Initialize session cache.

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
        """Ensure session_cache table exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = self._get_conn()
        try:
            schema_path = Path(__file__).parent / 'schema.sql'
            if schema_path.exists():
                conn.executescript(schema_path.read_text())
            conn.commit()
        finally:
            conn.close()

    def store_session(
        self,
        teacher_id: int,
        cookies: List[Dict[str, Any]],
        csrf_token: Optional[str] = None,
        expires_in_hours: int = 6
    ) -> bool:
        """
        Store authentication session for a teacher.

        Args:
            teacher_id: Teacher database ID.
            cookies: List of cookie dicts from Playwright.
            csrf_token: CSRF token from the MOEIS page.
            expires_in_hours: Session expiry (default: 6 hours).

        Returns:
            True if stored successfully.
        """
        now = datetime.now()
        expires_at = now + timedelta(hours=expires_in_hours)
        cookies_json = json.dumps(cookies)

        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO session_cache
                   (teacher_id, cookies, csrf_token, created_at, expires_at, last_used)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (teacher_id, cookies_json, csrf_token,
                 now.isoformat(), expires_at.isoformat(), now.isoformat())
            )
            conn.commit()

            self.logger.info(
                f"Stored session for teacher ID={teacher_id} "
                f"(expires: {expires_at.strftime('%Y-%m-%d %H:%M')})"
            )
            return True
        except sqlite3.Error as e:
            self.logger.error(f"Failed to store session: {e}")
            return False
        finally:
            conn.close()

    def get_session(self, teacher_id: int) -> Optional[Dict[str, Any]]:
        """
        Get valid (non-expired) session for a teacher.

        Args:
            teacher_id: Teacher database ID.

        Returns:
            Session dict or None if not found/expired.
            {
                'teacher_id': 1,
                'cookies': [...],
                'csrf_token': 'abc123',
                'created_at': '2024-01-15T08:00:00',
                'expires_at': '2024-01-15T14:00:00',
            }
        """
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT teacher_id, cookies, csrf_token, created_at, expires_at "
                "FROM session_cache WHERE teacher_id = ?",
                (teacher_id,)
            ).fetchone()

            if not row:
                return None

            # Check expiry
            expires_at = datetime.fromisoformat(row['expires_at'])
            if datetime.now() > expires_at:
                self.logger.info(f"Session for teacher ID={teacher_id} has expired")
                return None

            # Update last_used
            conn.execute(
                "UPDATE session_cache SET last_used = ? WHERE teacher_id = ?",
                (datetime.now().isoformat(), teacher_id)
            )
            conn.commit()

            return {
                'teacher_id': row['teacher_id'],
                'cookies': json.loads(row['cookies']),
                'csrf_token': row['csrf_token'],
                'created_at': row['created_at'],
                'expires_at': row['expires_at'],
            }
        except sqlite3.Error as e:
            self.logger.error(f"Failed to get session: {e}")
            return None
        finally:
            conn.close()

    def delete_session(self, teacher_id: int) -> bool:
        """Delete session for a teacher."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM session_cache WHERE teacher_id = ?", (teacher_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def clear_expired(self) -> int:
        """Remove all expired sessions. Returns count deleted."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM session_cache WHERE expires_at < ?",
                (datetime.now().isoformat(),)
            )
            conn.commit()
            count = cursor.rowcount
            if count > 0:
                self.logger.info(f"Cleared {count} expired sessions")
            return count
        finally:
            conn.close()

    def clear_all(self) -> int:
        """Remove all sessions. Returns count deleted."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("DELETE FROM session_cache")
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
