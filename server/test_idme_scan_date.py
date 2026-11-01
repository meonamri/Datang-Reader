"""Offline-queued scans must be filed under their REAL scan date, and the IDME
login engine only accepts an ISO target date (regression tests, 2026-11-01)."""
import sqlite3
from datetime import datetime, date

import pytest

from src.idme.scan_tracker import ScanTracker
from src.offline_queue import AttendanceQueue
from src.idme.login_engine import IDMELoginEngine

RESP = {"name": "TEST PELAJAR", "section": "9 TEST", "pid": "p1", "time_text": ""}


def _dates(db):
    return dict(sqlite3.connect(db).execute(
        "select student_name, scan_date from daily_scans").fetchall())


def test_record_scan_uses_scanned_at_date(tmp_path):
    db = str(tmp_path / "idme.db")
    t = ScanTracker(db)
    assert t.record_scan("0000000001", RESP, scanned_at=datetime(2026, 10, 25, 7, 15))
    assert t.record_scan("0000000002", dict(RESP, name="LIVE PELAJAR"))
    rows = _dates(db)
    assert rows["TEST PELAJAR"] == "2026-10-25"
    assert rows["LIVE PELAJAR"] == date.today().isoformat()


def test_sync_passes_original_timestamp_to_hook(tmp_path):
    db = str(tmp_path / "idme.db")
    t = ScanTracker(db)
    q = AttendanceQueue(str(tmp_path / "q.db"))
    q.enqueue("0000000003", datetime(2026, 10, 26, 6, 50), None)

    class FakeAPI:
        def submit_attendance(self, card_id, timestamp=None, temperature=None):
            return {"name": "SYNC PELAJAR", "section": "9 TEST", "pid": "p3"}

    seen = []

    def hook(card_id, response, scanned_at):
        seen.append(scanned_at)
        t.record_scan(card_id, response, scanned_at=scanned_at)

    stats = q.sync_with_api(FakeAPI(), on_synced=hook)
    assert stats["synced"] == 1
    assert seen[0].date().isoformat() == "2026-10-26"
    assert _dates(db)["SYNC PELAJAR"] == "2026-10-26"


def test_login_engine_target_date_validation():
    assert IDMELoginEngine("x", "y").target_date is None
    assert IDMELoginEngine("x", "y", target_date="2026-10-26").target_date == "2026-10-26"
    with pytest.raises(ValueError):
        IDMELoginEngine("x", "y", target_date="26/10/2026")
