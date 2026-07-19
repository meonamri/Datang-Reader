"""
Unit tests for the "Hadir (lupa kad)" present-override feature.

Covers the two pieces of pure logic added for the remote-control request:

  * PresentOverrideStore — mark/clear/count. A same-day repeat tap stays one row
    (window count doesn't inflate); distinct days accumulate; the rolling window
    is a trailing look-back; clear_override removes the row.
  * AbsenceDetector — a present-override DROPS a student from detect_absences and
    counts them PRESENT in get_attendance_summary, so roster = present + absent
    still holds (the invariant the settings UI relies on).

Pure logic — no Playwright/network. The roster and scan sources are mocked; the
store runs against a real temp-file SQLite DB (an in-memory ":memory:" DB can't be
shared across the store's short-lived connections). Run directly
(`python test_idme_hadir.py`) or under pytest, from `server/` (e.g. .venv-idme).
"""

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.idme.present_override_store import PresentOverrideStore  # noqa: E402
from src.idme.absence_detector import AbsenceDetector  # noqa: E402


def _iso(d):
    return d.isoformat()


class PresentOverrideStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = PresentOverrideStore(str(Path(self._tmp.name) / "idme.db"))
        self.today = date(2026, 7, 20)

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_mark_returns_count_one(self):
        res = self.store.mark_present("5 UKM", "AHMAD BIN ALI",
                                      scan_date=_iso(self.today))
        self.assertEqual(res['window_count'], 1)
        self.assertEqual(res['student_name'], "AHMAD BIN ALI")

    def test_same_day_repeat_stays_one_row(self):
        for _ in range(3):
            res = self.store.mark_present("5 UKM", "AHMAD BIN ALI",
                                          scan_date=_iso(self.today))
        # Upsert on the same day must not inflate the window count.
        self.assertEqual(res['window_count'], 1)

    def test_distinct_days_accumulate_in_window(self):
        # Marks land chronologically (oldest → today), as they do in practice — a
        # Hadir tap is always for "today". The window ends at scan_date, so the
        # final mark (today) sees all 4 distinct days.
        for i in range(3, -1, -1):
            d = self.today - timedelta(days=i)
            res = self.store.mark_present("5 UKM", "AHMAD BIN ALI", scan_date=_iso(d))
        self.assertEqual(res['window_count'], 4)

    def test_window_excludes_days_outside_lookback(self):
        # Two marks 20 days apart; a 14-day window from the later date sees only 1.
        self.store.mark_present("5 UKM", "AHMAD BIN ALI",
                                scan_date=_iso(self.today - timedelta(days=20)))
        res = self.store.mark_present("5 UKM", "AHMAD BIN ALI",
                                      scan_date=_iso(self.today), window_days=14)
        self.assertEqual(res['window_count'], 1)

    def test_count_is_per_student(self):
        self.store.mark_present("5 UKM", "AHMAD BIN ALI", scan_date=_iso(self.today))
        res = self.store.mark_present("5 UKM", "SITI BINTI OMAR",
                                      scan_date=_iso(self.today))
        self.assertEqual(res['window_count'], 1)

    def test_clear_override_removes_row(self):
        self.store.mark_present("5 UKM", "AHMAD BIN ALI", scan_date=_iso(self.today))
        deleted = self.store.clear_override("5 UKM", "AHMAD BIN ALI",
                                            scan_date=_iso(self.today))
        self.assertTrue(deleted)
        self.assertEqual(
            self.store.get_overrides_for("5 UKM", _iso(self.today)), {})

    def test_get_overrides_indexed_by_id_and_name(self):
        self.store.mark_present("5 UKM", "Ahmad Bin Ali", scan_date=_iso(self.today),
                                idpelajar="12345")
        idx = self.store.get_overrides_for("5 UKM", _iso(self.today))
        self.assertTrue(idx.get(PresentOverrideStore.id_key("12345")))
        # Name key is normalized; stored uppercased.
        self.assertTrue(any(k.startswith("name:") for k in idx))


class DetectorOverrideTests(unittest.TestCase):
    """detect_absences / get_attendance_summary honor present-overrides."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = PresentOverrideStore(str(Path(self._tmp.name) / "idme.db"))
        self.today = "2026-07-20"

        self.roster = MagicMock()
        self.roster.get_class_roster.return_value = [
            {'name': 'AHMAD BIN ALI', 'integration_tag': None, 'idpelajar': None},
            {'name': 'SITI BINTI OMAR', 'integration_tag': None, 'idpelajar': None},
            {'name': 'RAJ A/L KUMAR', 'integration_tag': None, 'idpelajar': None},
        ]
        self.scans = MagicMock()
        # Only AHMAD actually scanned; SITI and RAJ are absent-by-scan.
        self.scans.get_scanned_tags.return_value = set()
        self.scans.get_scanned_students.return_value = ['AHMAD BIN ALI']

        self.detector = AbsenceDetector(
            self.roster, self.scans, reason_store=None, present_store=self.store)

    def tearDown(self):
        self._tmp.cleanup()

    def test_override_drops_student_from_absences(self):
        before = {a['student_name'] for a in
                  self.detector.detect_absences("5 UKM", self.today)}
        self.assertEqual(before, {'SITI BINTI OMAR', 'RAJ A/L KUMAR'})

        self.store.mark_present("5 UKM", "SITI BINTI OMAR", scan_date=self.today)
        after = {a['student_name'] for a in
                 self.detector.detect_absences("5 UKM", self.today)}
        self.assertEqual(after, {'RAJ A/L KUMAR'})

    def test_summary_counts_override_as_present(self):
        self.store.mark_present("5 UKM", "SITI BINTI OMAR", scan_date=self.today)
        summary = self.detector.get_attendance_summary("5 UKM", self.today)
        # roster = present + absent must hold: 3 = 2 present (AHMAD scanned +
        # SITI overridden) + 1 absent (RAJ).
        self.assertEqual(summary['roster_count'], 3)
        self.assertEqual(summary['scanned_count'], 2)
        self.assertEqual(summary['absent_count'], 1)
        self.assertIn('SITI BINTI OMAR', summary['scanned_students'])
        self.assertEqual(summary['absent_students'], ['RAJ A/L KUMAR'])

    def test_no_present_store_is_original_behaviour(self):
        detector = AbsenceDetector(self.roster, self.scans, present_store=None)
        self.store.mark_present("5 UKM", "SITI BINTI OMAR", scan_date=self.today)
        names = {a['student_name'] for a in
                 detector.detect_absences("5 UKM", self.today)}
        # Without a present_store nothing is dropped — the override is ignored.
        self.assertEqual(names, {'SITI BINTI OMAR', 'RAJ A/L KUMAR'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
