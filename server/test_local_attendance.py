"""Local attendance authority (src/local_attendance.py) — the school-owned
replacement for Datang.my's card lookup. See
documents/attendance-portal-plan.md §2 and the module docstring."""
import sqlite3
from datetime import datetime, timedelta

import pytest
import requests

from src.local_attendance import LocalAttendanceStore, DatangMirror
from src.api_client import NetworkError, AttendanceSubmissionError


def _db(tmp_path):
    return str(tmp_path / "idme_data.db")


def _add_student(db, name, cls, tag, idpelajar="ID1", enabled=1):
    c = sqlite3.connect(db)
    c.execute("INSERT INTO students (name, class_name, integration_tag, idpelajar, enabled) "
              "VALUES (?, ?, ?, ?, ?)", (name, cls, tag, idpelajar, enabled))
    c.commit()


def _q(db, sql, *a):
    return sqlite3.connect(db).execute(sql, a).fetchall()


@pytest.fixture
def store(tmp_path):
    s = LocalAttendanceStore(_db(tmp_path), mode="local")
    _add_student(s.db_path, "ALI BIN ABU", "5 UKM", "0001234567")
    return s


def test_roster_card_recorded_with_leading_zeros(store):
    r = store.record("0001234567")
    assert r["success"] and r["status"] == "recorded"
    assert r["data"]["name"] == "ALI BIN ABU" and r["data"]["section"] == "5 UKM"
    assert r["data"]["resolved_via"] == "roster"
    rows = _q(store.db_path, "SELECT student_name, class_name, integration_tag FROM daily_scans")
    assert rows == [("ALI BIN ABU", "5 UKM", "0001234567")]
    # a numerically-equal card without the zeros is a different card
    assert store.record("1234567")["status"] == "unknown_card"


def test_directory_covers_classes_without_a_roster(store):
    store.learn_from_datang("0000000042", {"name": "Siti", "section": "4 UKM", "pid": "p42"})
    r = store.record("0000000042")
    assert r["success"] and r["data"]["section"] == "4 UKM" and r["data"]["resolved_via"] == "directory"
    assert _q(store.db_path, "SELECT datang_pid FROM daily_scans WHERE integration_tag='0000000042'") == [("p42",)]


def test_unknown_card_is_rejected_and_kept_for_admin(store):
    r = store.record("9999999999")
    assert not r["success"] and r["status"] == "unknown_card"
    assert _q(store.db_path, "SELECT reason FROM unmatched_scans WHERE card_id='9999999999'") == [("unknown_card",)]
    assert _q(store.db_path, "SELECT COUNT(*) FROM daily_scans") == [(0,)]


def test_event_id_makes_resend_idempotent(store):
    a = store.record("0001234567", event_id="evt-1", reader_id="smksat02")
    b = store.record("0001234567", event_id="evt-1", reader_id="smksat02")
    assert a["status"] == b["status"] == "recorded" and b.get("replayed")
    assert _q(store.db_path, "SELECT COUNT(*) FROM attendance_events") == [(1,)]


def test_repeat_tap_counts_once_but_is_audited(store):
    store.record("0001234567")
    r = store.record("0001234567")
    assert r["success"] and r["status"] == "repeat"
    assert _q(store.db_path, "SELECT COUNT(*) FROM daily_scans") == [(1,)]
    assert _q(store.db_path, "SELECT COUNT(*) FROM attendance_events") == [(2,)]


def test_delayed_tap_filed_under_original_date(store):
    yesterday = datetime.now() - timedelta(days=1)
    r = store.record("0001234567", scanned_at=yesterday)
    assert r["status"] == "recorded"
    assert _q(store.db_path, "SELECT scan_date FROM daily_scans") == [(yesterday.date().isoformat(),)]


@pytest.mark.parametrize("delta", [timedelta(minutes=10), -timedelta(days=8)])
def test_implausible_timestamps_quarantined(store, delta):
    r = store.record("0001234567", scanned_at=datetime.now() + delta)
    assert not r["success"] and r["status"] == "quarantined"
    assert _q(store.db_path, "SELECT COUNT(*) FROM daily_scans") == [(0,)]


def test_shared_card_in_roster_is_never_guessed(store):
    _add_student(store.db_path, "AHMAD", "5 UKM", "0001234567", idpelajar="ID2")
    assert store.record("0001234567")["status"] == "unknown_card"


def test_roster_beats_directory(store):
    store.learn_from_datang("0001234567", {"name": "ALI BIN ABU", "section": "OLD CLASS"})
    assert store.record("0001234567")["data"]["section"] == "5 UKM"


def test_seed_from_history_uses_latest_and_never_overrides(tmp_path):
    s = LocalAttendanceStore(_db(tmp_path), mode="shadow")
    c = sqlite3.connect(s.db_path)
    c.executemany("INSERT INTO daily_scans (student_name, class_name, integration_tag, scan_time, scan_date) "
                  "VALUES (?, ?, ?, ?, ?)", [
                      ("MIRA", "3 UM", "0000000007", "2026-10-01T07:00:00", "2026-10-01"),
                      ("MIRA", "4 UM", "0000000007", "2026-10-20T07:00:00", "2026-10-20"),
                      ("BOB", "MENTARI 1", "0000000008", "2026-10-20T07:01:00", "2026-10-20")])
    c.commit()
    s.learn_from_datang("0000000008", {"name": "BOB", "section": "MENTARI 2"})
    assert s.seed_from_history() == 1
    d = dict((r[0], r[1]) for r in _q(s.db_path, "SELECT card_id, class_name FROM card_directory"))
    assert d == {"0000000007": "4 UM", "0000000008": "MENTARI 2"}
    assert s.seed_from_history() == 0


def test_admin_directory_rows_are_not_overwritten(store):
    c = sqlite3.connect(store.db_path)
    c.execute("INSERT INTO card_directory (card_id, student_name, class_name, source, first_seen, last_seen, "
              "updated_at) VALUES ('0000000050','FIXED','1 UM','admin','t','t','t')")
    c.commit()
    store.learn_from_datang("0000000050", {"name": "WRONG", "section": "9 X"})
    assert _q(store.db_path, "SELECT student_name, class_name, source FROM card_directory "
                             "WHERE card_id='0000000050'") == [("FIXED", "1 UM", "admin")]


def test_shadow_compare(tmp_path):
    s = LocalAttendanceStore(_db(tmp_path), mode="shadow")
    _add_student(s.db_path, "ALI", "5 UKM", "0000000001")
    _add_student(s.db_path, "MOVED", "2 UM", "0000000002")
    now = datetime.now()
    ok = lambda n, c: {"success": True, "online": True, "data": {"name": n, "section": c}}
    s.record_shadow("0000000001", now, "r1", ok("Ali", "5 UKM"))         # agree (name case differs)
    s.record_shadow("0000000002", now, "r1", ok("MOVED", "3 UM"))        # roster says 2 UM
    s.record_shadow("0000000003", now, "r1", {"success": False, "online": True, "message": "CARD_NOT_FOUND"})
    s.record_shadow("0000000004", now, "r1", {"success": True, "online": False, "queued": True})
    s.record_shadow("0000000005", now, "r1", ok("NEW KID", "4 UKM"))     # unknown before; learnt now
    out = s.compare(now.date().isoformat())
    assert out["taps"] == 5 and out["agree"] == 2 and out["datang_queued"] == 1
    assert [m["card_id"] for m in out["class_mismatch"]] == ["0000000002"]
    assert [m["card_id"] for m in out["datang_rejected"]] == ["0000000003"]
    assert out["local_unknown"] == []          # 0000000005 was learnt before resolving
    assert s.resolve("0000000005")["class_name"] == "4 UKM"


# ------------------------------------------------------------------ mirror
class FakeAPI:
    def __init__(self, behaviour):
        self.token, self.behaviour, self.calls = "tok", behaviour, []

    def submit_attendance(self, card_id, timestamp=None, temperature=None):
        self.calls.append(card_id)
        b = self.behaviour
        if b == "ok":
            return {"name": "X", "section": "Y"}
        try:
            if b == "connect":
                raise requests.exceptions.ConnectionError("refused")
            if b == "readtimeout":
                raise requests.exceptions.ReadTimeout("30s")
        except requests.exceptions.RequestException as e:
            raise NetworkError(f"Network error: {e}")
        if b == "502":
            raise AttendanceSubmissionError("Server error: <html>502</html>")
        if b == "notfound":
            raise AttendanceSubmissionError("CARD_NOT_FOUND: no such tag")


class FakeAuth:
    def ensure_authenticated(self, force_login=False):
        return True


@pytest.mark.parametrize("behaviour,expected", [
    ("ok", "sent"), ("connect", "retry"), ("readtimeout", "uncertain"),
    ("502", "uncertain"), ("notfound", "rejected")])
def test_mirror_classification(store, behaviour, expected):
    store.record("0001234567", mirror=True)
    api = FakeAPI(behaviour)
    DatangMirror(store, api, FakeAuth()).drain_once()
    assert _q(store.db_path, "SELECT mirror_status FROM attendance_events") == [(expected,)]
    # a second pass resends only what provably never reached Datang.my
    DatangMirror(store, api, FakeAuth()).drain_once()
    assert len(api.calls) == (2 if expected == "retry" else 1)


def test_mirror_never_forwards_another_days_tap(store):
    store.record("0001234567", scanned_at=datetime.now() - timedelta(days=1), mirror=True)
    api = FakeAPI("ok")
    DatangMirror(store, api, FakeAuth()).drain_once()
    assert api.calls == []
    assert _q(store.db_path, "SELECT mirror_status FROM attendance_events") == [("stale",)]


def test_unknown_cards_are_not_mirrored(store):
    store.record("9999999999", mirror=True)
    assert _q(store.db_path, "SELECT mirror_status FROM attendance_events") == [(None,)]


# ---------------------------------------------------------- ServiceManager
def _service_manager(monkeypatch, tmp_path, mode, mirror="false"):
    monkeypatch.setenv("ATTENDANCE_MODE", mode)
    monkeypatch.setenv("ATTENDANCE_DATANG_MIRROR", mirror)
    monkeypatch.setenv("ATTENDANCE_DB_PATH", _db(tmp_path))
    from src.config import Config
    monkeypatch.setattr(Config, "DATABASE_FILE", str(tmp_path / "queue.db"))
    from src.service_manager import ServiceManager
    return ServiceManager()


def test_local_mode_never_calls_datang(monkeypatch, tmp_path):
    sm = _service_manager(monkeypatch, tmp_path, "local")
    _add_student(_db(tmp_path), "ALI", "5 UKM", "0000000001")

    def boom(*a, **k):
        raise AssertionError("Datang.my must not be contacted in local mode")
    sm.api_client.submit_attendance = boom
    r = sm.process_attendance("0000000001", event_id="e1", reader_id="smksat01")
    assert r["success"] and r["online"] and r["data"]["name"] == "ALI"


def test_shadow_mode_keeps_datang_answer_and_logs_local(monkeypatch, tmp_path):
    sm = _service_manager(monkeypatch, tmp_path, "shadow")
    sm.api_client.token = "tok"
    sm.api_client.submit_attendance = lambda **k: {"name": "NEW KID", "section": "4 UKM", "pid": "p"}
    r = sm.process_attendance("0000000009")
    assert r["success"] and r["data"]["name"] == "NEW KID"
    assert sm.local_attendance.resolve("0000000009")["class_name"] == "4 UKM"
    assert sm.local_attendance.compare(datetime.now().date().isoformat())["agree"] == 1


def test_shadow_logging_failure_never_breaks_a_tap(monkeypatch, tmp_path):
    sm = _service_manager(monkeypatch, tmp_path, "shadow")
    sm.api_client.token = "tok"
    sm.api_client.submit_attendance = lambda **k: {"name": "A", "section": "B"}

    def broken(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")
    sm.local_attendance.record_shadow = broken
    assert sm.process_attendance("0000000009")["success"]


def test_default_mode_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.delenv("ATTENDANCE_MODE", raising=False)
    sm = _service_manager(monkeypatch, tmp_path, "datang")
    assert sm.attendance_mode == "datang" and sm.local_attendance is None
