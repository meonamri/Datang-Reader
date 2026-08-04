"""
Unit tests for retiring dropped students on "Read portal"
(RosterManager.upsert_from_portal).

A student who leaves the school disappears from the MOEIS student table but used
to stay `enabled = 1` in the local registry. AbsenceDetector then submitted them
absent every day, and the portal had no checkbox to mark ("Student checkbox not
found") — which fails the WHOLE class submission, permanently. Observed in prod
on 2026-08-03 for 2 UTM and 3 UTM.

upsert_from_portal now retires them (enabled = 0). Covered here:

  * a student the portal no longer lists is retired, and drops out of
    get_class_roster;
  * the retirement is a SOFT delete — the row and its learned RFID tag survive;
  * a retired student the portal lists again is RE-ENABLED (matched by idpelajar
    even though the row is disabled), tag intact;
  * an empty portal list never retires anyone (a bad read is not authority);
  * other classes are untouched.

Pure SQLite, no Playwright/network. Runs against a real temp-file DB (the
manager opens short-lived connections, so ":memory:" can't be shared). Run
directly (`python test_idme_roster_retire.py`) or under pytest, from `server/`.
"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.idme.roster_manager import RosterManager  # noqa: E402


class RetireDroppedStudentTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "idme.db")
        self.rm = RosterManager(self.db_path)

        # Seed 2 UTM the way a first portal read would, plus a second class that
        # must stay untouched.
        self.rm.upsert_from_portal("2 UTM", [
            {'id': 'M001', 'name': 'ARIF AIMAN HAZIQ BIN MOHAMAD SAAD'},
            {'id': 'M002', 'name': 'NURUL SYIFA SYARDILLA BINTI MOHD SHAUKHI'},
        ])
        self.rm.upsert_from_portal("3 UTM", [
            {'id': 'M003', 'name': 'MUHAMAD KHAIRUL AQIL BIN HASIM'},
        ])

    def tearDown(self):
        self._tmp.cleanup()

    # --- helpers ---------------------------------------------------------

    def _row(self, name):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(
                "SELECT * FROM students WHERE name = ?", (name,)
            ).fetchone()
        finally:
            conn.close()

    def _set_tag(self, name, tag):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE students SET integration_tag = ?, tag_source = 'learned' "
                "WHERE name = ?", (tag, name)
            )
            conn.commit()
        finally:
            conn.close()

    def _names(self, class_name):
        return {s['name'] for s in self.rm.get_class_roster(class_name)}

    # --- tests -----------------------------------------------------------

    def test_dropped_student_is_retired_and_reported(self):
        result = self.rm.upsert_from_portal("2 UTM", [
            {'id': 'M001', 'name': 'ARIF AIMAN HAZIQ BIN MOHAMAD SAAD'},
        ])

        self.assertEqual(
            result['removed'], ['NURUL SYIFA SYARDILLA BINTI MOHD SHAUKHI']
        )
        row = self._row('NURUL SYIFA SYARDILLA BINTI MOHD SHAUKHI')
        self.assertEqual(row['enabled'], 0)

    def test_retired_student_leaves_the_active_roster(self):
        # This is the bit that stops the daily false absence: get_class_roster
        # is what AbsenceDetector counts against.
        self.rm.upsert_from_portal("2 UTM", [
            {'id': 'M001', 'name': 'ARIF AIMAN HAZIQ BIN MOHAMAD SAAD'},
        ])
        self.assertEqual(
            self._names("2 UTM"), {'ARIF AIMAN HAZIQ BIN MOHAMAD SAAD'}
        )

    def test_retire_is_soft__row_and_learned_tag_survive(self):
        self._set_tag('NURUL SYIFA SYARDILLA BINTI MOHD SHAUKHI', 'TAG-99')
        self.rm.upsert_from_portal("2 UTM", [
            {'id': 'M001', 'name': 'ARIF AIMAN HAZIQ BIN MOHAMAD SAAD'},
        ])

        row = self._row('NURUL SYIFA SYARDILLA BINTI MOHD SHAUKHI')
        self.assertIsNotNone(row, "retire must not DELETE the row")
        self.assertEqual(row['integration_tag'], 'TAG-99')
        self.assertEqual(row['tag_source'], 'learned')

    def test_returning_student_is_re_enabled_with_tag_intact(self):
        self._set_tag('NURUL SYIFA SYARDILLA BINTI MOHD SHAUKHI', 'TAG-99')
        self.rm.upsert_from_portal("2 UTM", [
            {'id': 'M001', 'name': 'ARIF AIMAN HAZIQ BIN MOHAMAD SAAD'},
        ])

        # Portal lists them again — matched by idpelajar despite enabled = 0.
        result = self.rm.upsert_from_portal("2 UTM", [
            {'id': 'M001', 'name': 'ARIF AIMAN HAZIQ BIN MOHAMAD SAAD'},
            {'id': 'M002', 'name': 'NURUL SYIFA SYARDILLA BINTI MOHD SHAUKHI'},
        ])

        self.assertEqual(result['added'], 0, "must re-enable, not duplicate")
        self.assertEqual(result['removed'], [])
        row = self._row('NURUL SYIFA SYARDILLA BINTI MOHD SHAUKHI')
        self.assertEqual(row['enabled'], 1)
        self.assertEqual(row['integration_tag'], 'TAG-99')
        self.assertIn('NURUL SYIFA SYARDILLA BINTI MOHD SHAUKHI',
                      self._names("2 UTM"))

    def test_empty_portal_list_retires_nobody(self):
        # A failed/empty read must never wipe a class.
        result = self.rm.upsert_from_portal("2 UTM", [])

        self.assertEqual(result['removed'], [])
        self.assertEqual(len(self._names("2 UTM")), 2)

    def test_other_classes_are_untouched(self):
        self.rm.upsert_from_portal("2 UTM", [
            {'id': 'M001', 'name': 'ARIF AIMAN HAZIQ BIN MOHAMAD SAAD'},
        ])
        self.assertEqual(
            self._names("3 UTM"), {'MUHAMAD KHAIRUL AQIL BIN HASIM'}
        )

    def test_rename_is_not_a_retire(self):
        # Same idpelajar, corrected spelling: an update, not a drop.
        result = self.rm.upsert_from_portal("2 UTM", [
            {'id': 'M001', 'name': 'ARIF AIMAN HAZIQ BIN MOHAMAD SAAD'},
            {'id': 'M002', 'name': 'NURUL SYIFA SYARDILLA BINTI MOHD SHAUKRI'},
        ])

        self.assertEqual(result['removed'], [])
        self.assertEqual(len(result['renamed']), 1)
        self.assertEqual(len(self._names("2 UTM")), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
