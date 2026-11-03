"""
Reader-side outbox: every tap is written to a local SQLite file BEFORE the
reader talks to the server, so a tap survives a server/network outage, a GUI
crash or a reboot, and is delivered later with its original time.

Lifecycle of one row (`taps` table):

  pending    saved, not yet answered by the server; the sync loop retries it
  delivered  the server gave a final answer (recorded, or refused e.g. unknown card)
  uncertain  the server may or may not have recorded it and does NOT support
             idempotent resends, so we refuse to resend (avoid a duplicate);
             visible in the status file for the office to check

Every tap carries a uuid `event_id`; a server that advertises the
`card_event_id` capability (GET /status -> capabilities) answers a resent
event with its first result instead of recording it twice. Resends after an
ambiguous failure (read timeout, 5xx) are only made to such a server.

No Qt here: the GUI drives it from its own threads and this module is
unit-tested on its own.
"""

from __future__ import annotations

import json
import socket
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

SCHEMA = """
CREATE TABLE IF NOT EXISTS taps (
    event_id      TEXT PRIMARY KEY,
    card_id       TEXT NOT NULL,
    scanned_at    TEXT NOT NULL,          -- ISO-8601 with UTC offset
    reader_id     TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    attempts      INTEGER NOT NULL DEFAULT 0,
    next_attempt  TEXT NOT NULL,          -- ISO, local naive
    last_error    TEXT,
    result        TEXT,                   -- JSON body of the final answer
    delivered_at  TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_taps_status ON taps(status, next_attempt);
"""

MAX_BACKOFF_S = 300
KEEP_DELIVERED_DAYS = 30

# Delivery verdicts
FINAL = "final"              # server answered; do not resend
RETRY = "retry"              # never reached the server; resend is always safe
AMBIGUOUS = "ambiguous"      # may have been recorded; resend only if idempotent


def classify_response(status_code: int, body: Optional[Dict[str, Any]]) -> str:
    if status_code == 200 and isinstance(body, dict) and "success" in body:
        return FINAL
    if status_code == 400:
        return FINAL             # malformed request; resending cannot help
    if status_code == 409:
        return RETRY             # server still processing this event_id
    return AMBIGUOUS


class Outbox:
    def __init__(self, path: str, reader_id: Optional[str] = None):
        self.path = path
        self.reader_id = reader_id or socket.gethostname()
        conn = self._conn()
        try:
            conn.executescript(SCHEMA)
        finally:
            conn.close()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")   # a saved tap must survive power loss
        return conn

    # ------------------------------------------------------------ writing
    def add(self, card_id: str, when: Optional[datetime] = None,
            hold_seconds: float = 0) -> Dict[str, Any]:
        """Save a tap. `hold_seconds` keeps the sync loop off it while the
        caller tries to deliver it right now (so it is never sent twice in
        parallel)."""
        when = when or datetime.now().astimezone()
        if when.tzinfo is None:
            when = when.astimezone()
        row = {
            "event_id": uuid.uuid4().hex,
            "card_id": card_id,
            "scanned_at": when.isoformat(timespec="seconds"),
            "reader_id": self.reader_id,
        }
        now = datetime.now()
        conn = self._conn()
        try:
            conn.execute(
                "INSERT INTO taps (event_id, card_id, scanned_at, reader_id, next_attempt, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (row["event_id"], card_id, row["scanned_at"], self.reader_id,
                 (now + timedelta(seconds=hold_seconds)).isoformat(), now.isoformat()),
            )
        finally:
            conn.close()
        return row

    def get(self, event_id: str) -> Optional[sqlite3.Row]:
        conn = self._conn()
        try:
            return conn.execute("SELECT * FROM taps WHERE event_id = ?", (event_id,)).fetchone()
        finally:
            conn.close()

    def payload(self, row) -> Dict[str, Any]:
        return {"card_id": row["card_id"], "event_id": row["event_id"],
                "scanned_at": row["scanned_at"], "reader_id": row["reader_id"]}

    def mark_delivered(self, event_id: str, body: Dict[str, Any]) -> None:
        self._update(event_id, status="delivered", result=json.dumps(body)[:4000],
                     delivered_at=datetime.now().isoformat(), last_error=None)

    def mark_failed_attempt(self, event_id: str, error: str, resend_allowed: bool) -> None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT attempts FROM taps WHERE event_id = ?", (event_id,)).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            delay = min(MAX_BACKOFF_S, 5 * (2 ** min(attempts - 1, 6)))
            conn.execute(
                "UPDATE taps SET attempts = ?, last_error = ?, status = ?, next_attempt = ? WHERE event_id = ?",
                (attempts, error[:300], "pending" if resend_allowed else "uncertain",
                 (datetime.now() + timedelta(seconds=delay)).isoformat(), event_id),
            )
        finally:
            conn.close()

    def _update(self, event_id: str, **cols) -> None:
        sets = ", ".join(f"{k} = ?" for k in cols)
        conn = self._conn()
        try:
            conn.execute(f"UPDATE taps SET {sets} WHERE event_id = ?", (*cols.values(), event_id))
        finally:
            conn.close()

    # ------------------------------------------------------------ reading
    def due(self, limit: int = 20) -> List[sqlite3.Row]:
        conn = self._conn()
        try:
            return conn.execute(
                "SELECT * FROM taps WHERE status = 'pending' AND next_attempt <= ? "
                "ORDER BY scanned_at LIMIT ?",
                (datetime.now().isoformat(), limit),
            ).fetchall()
        finally:
            conn.close()

    def counts(self) -> Dict[str, Any]:
        conn = self._conn()
        try:
            by = dict(conn.execute("SELECT status, COUNT(*) FROM taps GROUP BY status").fetchall())
            oldest = conn.execute("SELECT MIN(scanned_at) FROM taps WHERE status = 'pending'").fetchone()[0]
        finally:
            conn.close()
        return {"pending": by.get("pending", 0), "uncertain": by.get("uncertain", 0),
                "delivered": by.get("delivered", 0), "oldest_pending": oldest}

    def purge(self, days: int = KEEP_DELIVERED_DAYS) -> int:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        conn = self._conn()
        try:
            return conn.execute(
                "DELETE FROM taps WHERE status = 'delivered' AND delivered_at < ?", (cutoff,)
            ).rowcount
        finally:
            conn.close()


def deliver(outbox: Outbox, row, card_url: str, timeout: float,
            server_idempotent: bool) -> Tuple[str, Optional[Dict[str, Any]], str]:
    """POST one saved tap. Updates the outbox and returns
    (verdict, body_or_None, error_text)."""
    try:
        resp = requests.post(card_url, json=outbox.payload(row), timeout=timeout)
    except requests.exceptions.ReadTimeout as e:
        verdict, body, err = AMBIGUOUS, None, f"timeout: {e}"
    except requests.exceptions.ConnectionError as e:
        # includes ConnectTimeout: the request never reached the server
        verdict, body, err = RETRY, None, f"unreachable: {e}"
    except requests.exceptions.RequestException as e:
        verdict, body, err = AMBIGUOUS, None, f"{type(e).__name__}: {e}"
    else:
        try:
            body = resp.json()
        except ValueError:
            body = None
        verdict = classify_response(resp.status_code, body)
        err = "" if verdict == FINAL else f"HTTP {resp.status_code}"

    if verdict == FINAL:
        outbox.mark_delivered(row["event_id"], body)
    else:
        outbox.mark_failed_attempt(row["event_id"], err,
                                   resend_allowed=(verdict == RETRY or server_idempotent))
    return verdict, body, err


def sync_due(outbox: Outbox, card_url: str, timeout: float, server_idempotent: bool,
             limit: int = 20) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Deliver due taps oldest-first. Stops at the first tap that did not get
    a final answer (the server is evidently unhealthy). Returns
    [(row_as_dict, body)] for taps that got a final answer this pass."""
    finished = []
    for row in outbox.due(limit):
        verdict, body, _ = deliver(outbox, row, card_url, timeout, server_idempotent)
        if verdict != FINAL:
            break
        finished.append((dict(row), body))
    return finished
