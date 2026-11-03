"""
Local attendance authority — the school-owned replacement for Datang.my's
card lookup (documents/attendance-portal-plan.md, §2 "Server recording").

Datang.my does two things for us on every tap: it resolves an RFID card to a
student ({name, section, pid}) and it is the system of record for the tap.
This module does both locally, in the SAME SQLite file as the IDME module
(idme_data.db), so a tap and its `daily_scans` row commit atomically and the
IDME absence detector needs no changes.

Modes (env ATTENDANCE_MODE):

  datang  (default) Behaviour is unchanged; this module is not even constructed.
  shadow  Datang.my stays authoritative. Every tap is ALSO resolved locally and
          logged to `attendance_events` with both answers, so
          GET /attendance/compare can prove the local directory agrees with
          Datang.my before anyone flips the switch. Successful Datang responses
          teach the local `card_directory`.
  local   This module is authoritative. The request path never contacts
          Datang.my, so a Datang.my outage cannot fail a tap. With
          ATTENDANCE_DATANG_MIRROR=true (default) a single background worker
          forwards same-day taps to Datang.my so its dashboard keeps working
          during the pilot. Mirror outcomes that are UNCERTAIN (read timeout,
          5xx) are never replayed automatically.

Card resolution order: the MOEIS roster (`students.integration_tag`, carries
idpelajar) first, then `card_directory` — which covers classes that have no
IDME teacher and therefore no roster (e.g. 4 UKM, MENTARI 1 on 2026-11-02).
Card IDs are TEXT end to end, so leading zeros survive.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MODES = ("datang", "shadow", "local")

SCHEMA = """
CREATE TABLE IF NOT EXISTS card_directory (
    card_id      TEXT PRIMARY KEY,          -- RFID card id, TEXT (leading zeros)
    student_name TEXT NOT NULL,             -- uppercase, as Datang/roster spell it
    class_name   TEXT NOT NULL,
    datang_pid   TEXT,
    source       TEXT NOT NULL,             -- 'datang' | 'history' | 'admin'
    retired      INTEGER NOT NULL DEFAULT 0, -- 1 = lost/replaced card: refused at the reader
    first_seen   TIMESTAMP NOT NULL,
    last_seen    TIMESTAMP NOT NULL,
    updated_at   TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_card_directory_class ON card_directory(class_name);

-- One row per tap received, whatever happened to it (audit + idempotency).
CREATE TABLE IF NOT EXISTS attendance_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id      TEXT NOT NULL UNIQUE,     -- client-supplied or server uuid4
    card_id       TEXT NOT NULL,
    reader_id     TEXT,
    scanned_at    TIMESTAMP NOT NULL,       -- original tap time (local, naive)
    received_at   TIMESTAMP NOT NULL,
    scan_date     DATE NOT NULL,
    authority     TEXT NOT NULL,            -- 'local' | 'datang'
    status        TEXT NOT NULL,            -- recorded | repeat | unknown_card | quarantined
                                            -- (datang authority: datang_ok | datang_queued | datang_rejected)
    student_name  TEXT,                     -- answer used (local authority) / local answer (shadow)
    class_name    TEXT,
    resolved_via  TEXT,                     -- 'roster' | 'directory' | NULL
    datang_name   TEXT,                     -- shadow: what Datang.my said
    datang_class  TEXT,
    mirror_status TEXT,                     -- local+mirror: pending | sent | rejected | uncertain | retry | stale
    mirror_note   TEXT,
    mirror_at     TIMESTAMP,
    note          TEXT
);
CREATE INDEX IF NOT EXISTS idx_attendance_events_date ON attendance_events(scan_date);
CREATE INDEX IF NOT EXISTS idx_attendance_events_mirror ON attendance_events(mirror_status);

-- Every change made on the /cards admin screen.
CREATE TABLE IF NOT EXISTS card_audit (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TIMESTAMP NOT NULL,
    action     TEXT NOT NULL,               -- assign | retire
    card_id    TEXT NOT NULL,
    old_holder TEXT,                        -- "NAME (CLASS)" before the change
    new_holder TEXT,                        -- "NAME (CLASS)" after the change
    actor      TEXT,                        -- Tailscale login / typed name / client IP
    note       TEXT
);
CREATE INDEX IF NOT EXISTS idx_card_audit_card ON card_audit(card_id);
"""

# Plausibility window for a client-supplied tap time. Anything outside is kept
# for audit but never counted (plan: "quarantine implausible timestamps").
FUTURE_TOLERANCE = timedelta(minutes=2)
MAX_DELAY = timedelta(days=7)


def mode_from_env() -> str:
    mode = os.getenv("ATTENDANCE_MODE", "datang").strip().lower()
    if mode not in MODES:
        logger.error(f"Unknown ATTENDANCE_MODE={mode!r}; falling back to 'datang'")
        return "datang"
    return mode


def _now() -> datetime:
    return datetime.now()


def _parse_scanned_at(value: Any) -> Optional[datetime]:
    """ISO-8601 -> naive local datetime. Aware values are converted to the
    container's zone (TZ=Asia/Kuala_Lumpur), naive ones are taken as local."""
    if value is None or value == "":
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def datang_shaped(name: str, class_name: str, pid: Optional[str], ts: datetime) -> Dict[str, Any]:
    """The `data` dict Datang.my returns, so reader clients and ScanTracker
    keep working unchanged (client shows `name` and `section`)."""
    return {
        "pid": pid,
        "time": str(int(ts.timestamp() * 1000)),
        "time_text": ts.strftime("%H:%M:%S %d %B %Y"),
        "image": None,
        "name": name,
        "section": class_name,
        "group": "",
        "take_temperature": False,
        "temperature": False,
        "source": "local",
    }


class LocalAttendanceStore:
    """Card directory + authoritative tap log on top of idme_data.db."""

    def __init__(self, db_path: str, mode: str = "shadow"):
        # mode 'datang' = registry only (the /cards admin screen); taps are
        # still answered by Datang.my.
        if mode not in MODES:
            raise ValueError(f"LocalAttendanceStore mode must be one of {MODES}, got {mode!r}")
        self.db_path = Path(db_path)
        self.mode = mode
        self._ensure_db()

    # ---------------------------------------------------------------- schema
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    def _ensure_db(self) -> None:
        # Let ScanTracker create daily_scans/students/unmatched_scans + run the
        # IDME migrations, so this module works even with IDME disabled.
        from .idme.scan_tracker import ScanTracker
        ScanTracker(str(self.db_path))
        conn = self._conn()
        try:
            conn.executescript(SCHEMA)
        finally:
            conn.close()

    # -------------------------------------------------------- directory
    def seed_from_history(self) -> int:
        """Fill card_directory from daily_scans (every class Datang.my ever
        answered for, most recent spelling wins). Never overrides an existing
        row. Returns rows added."""
        conn = self._conn()
        try:
            now = _now().isoformat()
            cur = conn.execute(
                """INSERT OR IGNORE INTO card_directory
                   (card_id, student_name, class_name, datang_pid, source,
                    first_seen, last_seen, updated_at)
                   SELECT d.integration_tag, d.student_name, d.class_name,
                          d.datang_pid, 'history', MIN(d.scan_time), MAX(d.scan_time), ?
                   FROM daily_scans d
                   JOIN (SELECT integration_tag, MAX(scan_time) AS t FROM daily_scans
                         WHERE integration_tag IS NOT NULL AND integration_tag != ''
                         GROUP BY integration_tag) latest
                     ON latest.integration_tag = d.integration_tag AND latest.t = d.scan_time
                   GROUP BY d.integration_tag""",
                (now,),
            )
            added = cur.rowcount or 0
            if added:
                logger.info(f"card_directory seeded with {added} cards from scan history")
            return added
        finally:
            conn.close()

    def learn_from_datang(self, card_id: str, data: Dict[str, Any],
                          seen_at: Optional[datetime] = None) -> None:
        """Remember what Datang.my said about a card. 'admin' rows (set by a
        human resolving a conflict) are never overwritten."""
        name = (data or {}).get("name", "").strip().upper()
        section = (data or {}).get("section", "").strip()
        if not card_id or not name or not section:
            return
        ts = (seen_at or _now()).isoformat()
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO card_directory
                   (card_id, student_name, class_name, datang_pid, source,
                    first_seen, last_seen, updated_at)
                   VALUES (?, ?, ?, ?, 'datang', ?, ?, ?)
                   ON CONFLICT(card_id) DO UPDATE SET
                     student_name = CASE WHEN source = 'admin' THEN student_name ELSE excluded.student_name END,
                     class_name   = CASE WHEN source = 'admin' THEN class_name   ELSE excluded.class_name END,
                     datang_pid   = COALESCE(excluded.datang_pid, datang_pid),
                     source       = CASE WHEN source = 'admin' THEN source ELSE 'datang' END,
                     last_seen    = MAX(last_seen, excluded.last_seen),
                     updated_at   = excluded.updated_at""",
                (card_id, name, section, data.get("pid") or None, ts, ts, _now().isoformat()),
            )
        finally:
            conn.close()

    def resolve(self, card_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
        """card -> {name, class_name, pid, idpelajar, via} or None.
        A retired card resolves to {'retired': True, ...} and must be refused."""
        own = conn is None
        conn = conn or self._conn()
        try:
            retired = conn.execute(
                "SELECT student_name, class_name FROM card_directory WHERE card_id = ? AND retired = 1",
                (card_id,)).fetchone()
            if retired:
                return {"retired": True, "name": retired["student_name"],
                        "class_name": retired["class_name"], "via": "retired"}
            rows = conn.execute(
                "SELECT name, class_name, idpelajar FROM students "
                "WHERE integration_tag = ? AND enabled = 1",
                (card_id,),
            ).fetchall()
            directory = conn.execute(
                "SELECT student_name, class_name, datang_pid FROM card_directory WHERE card_id = ?",
                (card_id,),
            ).fetchone()
            pid = directory["datang_pid"] if directory else None
            if len(rows) == 1:
                r = rows[0]
                return {"name": r["name"].strip().upper(), "class_name": r["class_name"],
                        "pid": pid, "idpelajar": r["idpelajar"], "via": "roster"}
            if len(rows) > 1:
                # Two enabled students share a card: never guess.
                logger.warning(f"Card {card_id} maps to {len(rows)} roster students; treating as unknown")
                return None
            if directory:
                return {"name": directory["student_name"], "class_name": directory["class_name"],
                        "pid": pid, "idpelajar": None, "via": "directory"}
            return None
        finally:
            if own:
                conn.close()

    # ---------------------------------------------------- local authority
    def record(self, card_id: str, scanned_at: Optional[datetime] = None,
               reader_id: Optional[str] = None, event_id: Optional[str] = None,
               mirror: bool = False) -> Dict[str, Any]:
        """Authoritatively record one tap. Returns the /card response body
        (without timestamp). Idempotent on event_id."""
        received = _now()
        ts = scanned_at or received
        event_id = (event_id or "").strip() or uuid.uuid4().hex

        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute(
                "SELECT * FROM attendance_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if prior is not None:
                conn.execute("COMMIT")
                return self._response_for(prior, replay=True)

            status, note, who = None, None, None
            if ts > received + FUTURE_TOLERANCE or ts < received - MAX_DELAY:
                status, note = "quarantined", f"implausible scanned_at {ts.isoformat()}"
            else:
                who = self.resolve(card_id, conn)
                if who is not None and who.get("retired"):
                    status, note, who = "retired_card", f"retired card of {who['name']} ({who['class_name']})", None
                elif who is None:
                    status = "unknown_card"
                    conn.execute(
                        "INSERT OR IGNORE INTO unmatched_scans "
                        "(card_id, scan_name, scan_class, scan_date, reason) VALUES (?, '', NULL, ?, 'unknown_card')",
                        (card_id, ts.date().isoformat()),
                    )
                else:
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO daily_scans
                           (student_name, class_name, integration_tag, scan_time, scan_date, datang_pid)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (who["name"], who["class_name"], card_id, ts.isoformat(),
                         ts.date().isoformat(), who["pid"]),
                    )
                    status = "recorded" if cur.rowcount else "repeat"

            mirror_status = "pending" if (mirror and status in ("recorded", "repeat")) else None
            conn.execute(
                """INSERT INTO attendance_events
                   (event_id, card_id, reader_id, scanned_at, received_at, scan_date,
                    authority, status, student_name, class_name, resolved_via,
                    mirror_status, note)
                   VALUES (?, ?, ?, ?, ?, ?, 'local', ?, ?, ?, ?, ?, ?)""",
                (event_id, card_id, reader_id, ts.isoformat(), received.isoformat(),
                 ts.date().isoformat(), status,
                 who["name"] if who else None, who["class_name"] if who else None,
                 who["via"] if who else None, mirror_status, note),
            )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

        row = {"event_id": event_id, "status": status, "student_name": who and who["name"],
               "class_name": who and who["class_name"], "scanned_at": ts.isoformat(),
               "card_id": card_id, "note": note}
        resp = self._response_for(row)
        if who and status in ("recorded", "repeat"):
            resp["data"]["pid"] = who["pid"]
            resp["data"]["resolved_via"] = who["via"]
        return resp

    @staticmethod
    def _response_for(row, replay: bool = False) -> Dict[str, Any]:
        status = row["status"]
        base = {"event_id": row["event_id"], "status": status, "online": True, "authority": "local"}
        if replay:
            base["replayed"] = True
        if status in ("recorded", "repeat"):
            ts = datetime.fromisoformat(row["scanned_at"])
            return {**base, "success": True,
                    "message": "Attendance recorded!" if status == "recorded" else "Already recorded today",
                    "data": datang_shaped(row["student_name"], row["class_name"], None, ts)}
        if status == "unknown_card":
            return {**base, "success": False, "message": "CARD_NOT_FOUND: Kad tidak didaftarkan"}
        if status == "retired_card":
            return {**base, "success": False, "message": "CARD_RETIRED: Kad ini telah dibatalkan - sila ke pejabat"}
        return {**base, "success": False, "message": f"Tap time rejected ({row['note'] or status})"}

    # ----------------------------------------------------------- shadow
    def record_shadow(self, card_id: str, scanned_at: datetime, reader_id: Optional[str],
                      datang_result: Dict[str, Any]) -> None:
        """Log a Datang-authoritative tap next to our own answer for it."""
        data = datang_result.get("data") or {}
        if datang_result.get("success") and datang_result.get("online") and data.get("name"):
            status = "datang_ok"
            self.learn_from_datang(card_id, data, scanned_at)
        elif datang_result.get("queued"):
            status = "datang_queued"
        else:
            status = "datang_rejected"
        conn = self._conn()
        try:
            who = self.resolve(card_id, conn)
            if who is not None and who.get("retired"):
                who = None
            conn.execute(
                """INSERT INTO attendance_events
                   (event_id, card_id, reader_id, scanned_at, received_at, scan_date,
                    authority, status, student_name, class_name, resolved_via,
                    datang_name, datang_class, note)
                   VALUES (?, ?, ?, ?, ?, ?, 'datang', ?, ?, ?, ?, ?, ?, ?)""",
                (uuid.uuid4().hex, card_id, reader_id, scanned_at.isoformat(), _now().isoformat(),
                 scanned_at.date().isoformat(), status,
                 who and who["name"], who and who["class_name"], who and who["via"],
                 (data.get("name") or "").strip().upper() or None,
                 (data.get("section") or "").strip() or None,
                 None if status == "datang_ok" else str(datang_result.get("message", ""))[:300]),
            )
        finally:
            conn.close()

    def compare(self, scan_date: str) -> Dict[str, Any]:
        """Shadow-mode verdict for one day: would local authority have given
        the same answer Datang.my did?"""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT card_id, status, student_name, class_name, resolved_via, "
                "datang_name, datang_class, note FROM attendance_events "
                "WHERE authority = 'datang' AND scan_date = ? ORDER BY id",
                (scan_date,),
            ).fetchall()
        finally:
            conn.close()
        out = {"date": scan_date, "taps": len(rows), "agree": 0, "class_mismatch": [],
               "name_differs_same_class": 0, "local_unknown": [], "datang_rejected": [],
               "datang_queued": 0}
        for r in rows:
            if r["status"] == "datang_queued":
                out["datang_queued"] += 1
                continue
            if r["status"] == "datang_rejected":
                out["datang_rejected"].append({"card_id": r["card_id"], "local": r["student_name"],
                                               "local_class": r["class_name"], "datang_said": r["note"]})
                continue
            if r["student_name"] is None:
                out["local_unknown"].append({"card_id": r["card_id"], "datang_name": r["datang_name"],
                                             "datang_class": r["datang_class"]})
            elif r["class_name"] != r["datang_class"]:
                out["class_mismatch"].append({"card_id": r["card_id"], "local": r["student_name"],
                                              "local_class": r["class_name"], "via": r["resolved_via"],
                                              "datang_name": r["datang_name"],
                                              "datang_class": r["datang_class"]})
            else:
                out["agree"] += 1
                if r["student_name"] != r["datang_name"]:
                    out["name_differs_same_class"] += 1
        decided = out["agree"] + len(out["class_mismatch"]) + len(out["local_unknown"])
        out["agreement_pct"] = round(100.0 * out["agree"] / decided, 2) if decided else None
        return out

    # ----------------------------------------------------------- status
    def stats(self, scan_date: Optional[str] = None) -> Dict[str, Any]:
        scan_date = scan_date or _now().date().isoformat()
        conn = self._conn()
        try:
            by_status = dict(conn.execute(
                "SELECT status, COUNT(*) FROM attendance_events WHERE scan_date = ? GROUP BY status",
                (scan_date,)).fetchall())
            mirror = dict(conn.execute(
                "SELECT mirror_status, COUNT(*) FROM attendance_events "
                "WHERE mirror_status IS NOT NULL GROUP BY mirror_status").fetchall())
            directory = conn.execute("SELECT COUNT(*) FROM card_directory").fetchone()[0]
            roster_tags = conn.execute(
                "SELECT COUNT(*) FROM students WHERE enabled = 1 AND integration_tag IS NOT NULL"
            ).fetchone()[0]
            oldest_pending = conn.execute(
                "SELECT MIN(received_at) FROM attendance_events WHERE mirror_status IN ('pending','retry')"
            ).fetchone()[0]
        finally:
            conn.close()
        return {"mode": self.mode, "date": scan_date, "events_today": by_status,
                "mirror": mirror, "mirror_oldest_pending": oldest_pending,
                "card_directory": directory, "roster_cards": roster_tags}

    # ------------------------------------------------------------ mirror
    def mirror_batch(self) -> List[sqlite3.Row]:
        conn = self._conn()
        try:
            return conn.execute(
                "SELECT id, card_id, scanned_at, scan_date FROM attendance_events "
                "WHERE mirror_status IN ('pending', 'retry') ORDER BY id LIMIT 20"
            ).fetchall()
        finally:
            conn.close()

    def set_mirror(self, row_id: int, status: str, note: Optional[str] = None) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE attendance_events SET mirror_status = ?, mirror_note = ?, mirror_at = ? WHERE id = ?",
                (status, (note or "")[:300] or None, _now().isoformat(), row_id),
            )
        finally:
            conn.close()


class DatangMirror:
    """Single background worker forwarding locally-recorded taps to Datang.my.

    Datang.my's /scan takes no timestamp — it stamps arrival time itself — so a
    tap is only forwarded on its own day ('stale' otherwise). Classification is
    deliberately conservative (memory: never auto-replay a 502/timeout):
      sent       2xx with data
      rejected   Datang.my answered with an explicit error body (e.g. card unknown)
      retry      the request never reached Datang.my (connect error) — safe to resend
      uncertain  read timeout / 5xx / anything else — NOT resent; reconcile by hand
    """

    def __init__(self, store: LocalAttendanceStore, api_client, auth_manager,
                 interval: float = 5.0):
        self.store = store
        self.api = api_client
        self.auth = auth_manager
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="datang-mirror", daemon=True)
        self._thread.start()
        logger.info("Datang.my mirror worker started")

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.drain_once()
            except Exception as e:  # never let the worker die
                logger.error(f"Datang mirror pass failed: {e}")
            self._stop.wait(self.interval)

    def drain_once(self) -> int:
        import requests
        from .api_client import AuthenticationError, AttendanceSubmissionError, NetworkError

        today = _now().date().isoformat()
        sent = 0
        for row in self.store.mirror_batch():
            if row["scan_date"] != today:
                self.store.set_mirror(row["id"], "stale", "not forwarded: Datang.my would stamp the wrong day")
                continue
            if not self.api.token and not self.auth.ensure_authenticated():
                return sent  # Datang.my login down: leave pending, try next pass
            try:
                self.api.submit_attendance(card_id=row["card_id"],
                                           timestamp=datetime.fromisoformat(row["scanned_at"]))
                self.store.set_mirror(row["id"], "sent")
                sent += 1
            except AuthenticationError as e:
                # Token rejected before the scan was accepted; resend after re-login.
                self.api.token = None
                self.store.set_mirror(row["id"], "retry", f"auth: {e}")
                return sent
            except NetworkError as e:
                cause = e.__context__
                never_sent = isinstance(cause, requests.exceptions.ConnectionError) and not isinstance(
                    cause, requests.exceptions.ReadTimeout)
                self.store.set_mirror(row["id"], "retry" if never_sent else "uncertain", str(e))
                if never_sent:
                    return sent  # Datang.my unreachable; back off until next pass
            except AttendanceSubmissionError as e:
                # Only an explicit Datang.my error body is a clean rejection;
                # a 5xx or an unparseable 200 may still have been accepted.
                msg = str(e)
                unsure = msg.startswith("Server error") or msg.startswith("Invalid response format")
                self.store.set_mirror(row["id"], "uncertain" if unsure else "rejected", msg)
            except Exception as e:
                self.store.set_mirror(row["id"], "uncertain", f"{type(e).__name__}: {e}")
        return sent
