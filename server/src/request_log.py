"""
Idempotency for POST /card, in EVERY attendance mode.

A reader outbox resends a tap (same `event_id`) when it never got an answer —
e.g. its 5 s timeout fired while this server was still waiting up to 30 s on
Datang.my. Without this table that resend would be a second submission to
Datang.my. With it:

  first request     -> row 'processing', handled, result stored, row 'done'
  resend, done      -> the stored result, flagged "replayed": true
  resend, processing-> HTTP 409 (reader keeps it pending and retries later)
  processing > STALE_AFTER (worker died mid-tap) -> final "uncertain" answer;
                       it is NOT reprocessed, because Datang.my may already
                       have accepted it.

Lives in the legacy queue DB (Config.DATABASE_FILE), which exists in all modes.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

STALE_AFTER = timedelta(minutes=10)
KEEP_DAYS = 30


class RequestLog:
    def __init__(self, db_file: str):
        self.db_file = db_file
        conn = self._conn()
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS card_requests (
                       event_id   TEXT PRIMARY KEY,
                       card_id    TEXT NOT NULL,
                       state      TEXT NOT NULL,      -- processing | done
                       result     TEXT,
                       created_at TEXT NOT NULL,
                       done_at    TEXT)""")
        finally:
            conn.close()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def begin(self, event_id: str, card_id: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        """('new', None) -> caller processes then calls finish();
        ('done', result) -> return result; ('busy', None) -> 409."""
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM card_requests WHERE event_id = ?", (event_id,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO card_requests (event_id, card_id, state, created_at) VALUES (?, ?, 'processing', ?)",
                    (event_id, card_id, datetime.now().isoformat()))
                conn.execute("COMMIT")
                return "new", None
            conn.execute("COMMIT")
            if row["state"] == "done":
                return "done", {**json.loads(row["result"]), "replayed": True}
            if datetime.now() - datetime.fromisoformat(row["created_at"]) > STALE_AFTER:
                return "done", {"success": False, "online": True, "status": "uncertain", "replayed": True,
                                "message": "Outcome unknown - please check with the office"}
            return "busy", None
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def finish(self, event_id: str, result: Dict[str, Any]) -> None:
        conn = self._conn()
        try:
            conn.execute("UPDATE card_requests SET state = 'done', result = ?, done_at = ? WHERE event_id = ?",
                         (json.dumps(result, default=str), datetime.now().isoformat(), event_id))
            conn.execute("DELETE FROM card_requests WHERE created_at < ?",
                         ((datetime.now() - timedelta(days=KEEP_DAYS)).isoformat(),))
        finally:
            conn.close()
