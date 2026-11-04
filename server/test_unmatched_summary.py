"""Unmatched-scan alerts: counted per card, and settled once the card is mapped.

The coverage panel used to count unresolved unmatched_scans ROWS. A row is
written per card per day and was only resolved by the /cards screen, so the
number grew by one per unmapped card per school day and kept rows for cards
that were later learned or imported (11,069 rows / 73 real cards on 2026-11-04).
"""
import sqlite3

import pytest

from src.idme.scan_tracker import ScanTracker
from src.local_attendance import LocalAttendanceStore


def _add_student(db, name, cls, tag=None, source=None, enabled=1):
    c = sqlite3.connect(db)
    cur = c.execute("INSERT INTO students (name, class_name, integration_tag, tag_source, enabled) "
                    "VALUES (?, ?, ?, ?, ?)", (name, cls, tag, source, enabled))
    c.commit()
    return cur.lastrowid


def _unmatched(db, card_id, day, reason="no_match", cls="5 UKM"):
    c = sqlite3.connect(db)
    c.execute("INSERT INTO unmatched_scans (card_id, scan_name, scan_class, scan_date, reason) "
              "VALUES (?, 'X', ?, ?, ?)", (card_id, cls, day, reason))
    c.commit()


def _q(db, sql, *a):
    return sqlite3.connect(db).execute(sql, a).fetchall()


@pytest.fixture
def db(tmp_path):
    return LocalAttendanceStore(str(tmp_path / "idme.db"), mode="local").db_path


def test_summary_counts_cards_not_daily_rows(db):
    for day in ("2026-11-02", "2026-11-03", "2026-11-04"):
        _unmatched(db, "0000000001", day)
    _unmatched(db, "0000000002", "2026-11-04")
    s = ScanTracker(str(db)).get_unmatched_summary()
    assert (s["no_match"], s["total"], s["rows"]) == (2, 2, 4)


def test_summary_skips_cards_since_mapped_to_an_enabled_student(db):
    _unmatched(db, "0000000001", "2026-09-01")          # later imported via roster
    _unmatched(db, "0000000003", "2026-09-01")          # holder is disabled -> still pending
    _add_student(db, "ALI", "5 UKM", tag="0000000001", source="roster")
    _add_student(db, "OLD", "5 UKM", tag="0000000003", source="roster", enabled=0)
    s = ScanTracker(str(db)).get_unmatched_summary()
    assert (s["no_match"], s["total"]) == (1, 1)


def test_learning_a_tag_resolves_the_cards_old_alerts(db):
    _unmatched(db, "0000000001", "2026-11-03")
    _add_student(db, "ALI", "5 UKM")
    ScanTracker(str(db)).record_scan("0000000001", {"name": "ALI", "section": "5 UKM"})
    assert _q(db, "select resolved from unmatched_scans where card_id='0000000001'") == [(1,)]


def test_already_mapped_card_resolves_its_old_alerts(db):
    _unmatched(db, "0000000001", "2026-11-03")
    _add_student(db, "ALI", "5 UKM", tag="0000000001", source="learned")
    ScanTracker(str(db)).record_scan("0000000001", {"name": "ALI", "section": "5 UKM"})
    assert _q(db, "select resolved from unmatched_scans where card_id='0000000001'") == [(1,)]


def test_admin_kept_card_does_not_resolve_the_other_cards_alerts(db):
    _unmatched(db, "0000000009", "2026-11-03")
    _add_student(db, "ALI", "5 UKM", tag="0000000002", source="admin")
    ScanTracker(str(db)).record_scan("0000000009", {"name": "ALI", "section": "5 UKM"})
    assert _q(db, "select resolved from unmatched_scans where card_id='0000000009'") == [(0,)]


def test_unmatched_tap_still_records_an_alert(db):
    _add_student(db, "ALI", "5 UKM")
    ScanTracker(str(db)).record_scan("0000000005", {"name": "NOBODY", "section": "5 UKM"})
    assert _q(db, "select reason, resolved from unmatched_scans where card_id='0000000005'") == [("no_match", 0)]
