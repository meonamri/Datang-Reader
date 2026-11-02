"""
Unit tests for days already confirmed on the portal outside Datang.

When a teacher confirms a day by hand (TELAH DISAHKAN) before Datang submits it,
login_engine raises AlreadyConfirmedError on the locked day. The orchestrator
must record that as the terminal status 'confirmed_external' — not 'failed' —
with nothing written, never retried, and counted as done for the day.

Pure logic — the Playwright login/fill layer is mocked. Run directly
(`python test_idme_already_confirmed.py`) or under pytest, from `server/`.
"""

import asyncio
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.idme.orchestrator import IDMEOrchestrator  # noqa: E402
from src.idme.login_engine import AlreadyConfirmedError, LoginEngineError  # noqa: E402

_COMPONENTS = [
    "CredentialManager", "TeacherManager", "RosterManager",
    "ScanTracker", "AbsenceDetector", "SessionCache",
]

LOCKED_MSG = ("Attendance for 05/10/2026 is already confirmed (TELAH DISAHKAN); "
              "locked days are not edited by automation")


def _make_orchestrator():
    patchers = [patch(f"src.idme.orchestrator.{name}") for name in _COMPONENTS]
    for p in patchers:
        p.start()
    orch = IDMEOrchestrator(db_path=":memory:")
    orch._create_submission_record = MagicMock(return_value=1)
    orch._update_submission = MagicMock()
    orch._record_skip = MagicMock()
    orch._patchers = patchers
    return orch


def _stop(orch):
    for p in orch._patchers:
        p.stop()


def _prime(orch):
    orch.absence_detector.detect_absences.return_value = [
        {"student_name": "A", "category": "D", "sebab_id": "D0010075"}]
    orch.absence_detector.get_attendance_summary.return_value = {
        "roster_count": 25, "scanned_count": 24}
    orch._unanswered_absences = MagicMock(return_value=[])
    orch.teacher_manager.get_teacher_credentials.return_value = {
        "ic_number": "x", "password": "y"}


def _engine_raising(exc):
    engine = MagicMock()
    engine.login_and_navigate = AsyncMock(side_effect=exc)
    engine.close = AsyncMock()
    return engine


class AlreadyConfirmedStatusTests(unittest.TestCase):

    def _run(self, exc):
        orch = _make_orchestrator()
        try:
            _prime(orch)
            filler = MagicMock()
            with patch("src.idme.orchestrator.IDMELoginEngine",
                       return_value=_engine_raising(exc)), \
                 patch("src.idme.orchestrator.IDMEFormFiller",
                       return_value=filler):
                result = asyncio.run(
                    orch._submit_class_async(1, "5 USM", "2026-10-05", confirm=True))
            return orch, filler, result
        finally:
            _stop(orch)

    def test_locked_day_is_confirmed_external_not_failed(self):
        orch, filler, result = self._run(AlreadyConfirmedError(LOCKED_MSG))
        self.assertEqual(result["status"], "confirmed_external")
        self.assertFalse(result["retryable"])
        self.assertFalse(result["form_submitted"])
        self.assertFalse(result["write_attempted"])
        self.assertEqual(result["submitted"], 0)
        # Nothing touched the form.
        filler.mark_absences_and_submit.assert_not_called()
        # DB row ends in the new terminal status, never 'failed'.
        statuses = [c.kwargs.get("status") for c in orch._update_submission.call_args_list]
        self.assertIn("confirmed_external", statuses)
        self.assertNotIn("failed", statuses)

    def test_other_login_errors_still_fail(self):
        """Only the locked-day case changes; a generic portal error still fails."""
        orch = _make_orchestrator()
        try:
            _prime(orch)
            with patch("src.idme.orchestrator.IDMELoginEngine",
                       return_value=_engine_raising(
                           LoginEngineError("Not on MOEIS after SSO"))):
                with self.assertRaises(Exception):
                    asyncio.run(orch._submit_class_async(
                        1, "5 USM", "2026-10-05", confirm=True))
            statuses = [c.kwargs.get("status")
                        for c in orch._update_submission.call_args_list]
            self.assertIn("failed", statuses)
            self.assertNotIn("confirmed_external", statuses)
        finally:
            _stop(orch)

    def test_locked_message_still_classified_permanent(self):
        """A legacy 'failed' row with this message must never be auto-retried."""
        self.assertFalse(IDMEOrchestrator.is_transient_failure(
            "Submission failed: " + LOCKED_MSG))


class BulkAndDoneSetTests(unittest.TestCase):

    def test_bulk_run_does_not_retry_confirmed_external(self):
        orch = _make_orchestrator()
        try:
            orch.teacher_manager.get_all_teachers.return_value = [
                {"id": 1, "name": "T", "class_name": "5 USM"}]
            orch.init_roster_from_portal = MagicMock(return_value={
                "status": "completed", "roster_state": "current"})
            orch.submit_class = MagicMock(return_value={
                "class_name": "5 USM", "date": "2026-10-05",
                "status": "confirmed_external", "retryable": False})
            with patch("src.idme.orchestrator.time.sleep"):
                results = orch.submit_all_classes("2026-10-05", confirm=True)
            self.assertEqual(orch.submit_class.call_count, 1)
            self.assertEqual([r["status"] for r in results], ["confirmed_external"])
        finally:
            _stop(orch)

    def test_classes_completed_on_counts_confirmed_external(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "t.db")
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE idme_submissions (id INTEGER PRIMARY KEY, "
                         "class_name TEXT, submission_date TEXT, status TEXT)")
            conn.executemany(
                "INSERT INTO idme_submissions (class_name, submission_date, status) "
                "VALUES (?, ?, ?)",
                [("5 USM", "2026-10-05", "failed"),
                 ("5 USM", "2026-10-05", "confirmed_external"),
                 ("5 UM", "2026-10-05", "completed"),
                 ("4 UM", "2026-10-05", "failed")])
            conn.commit()
            conn.close()
            orch = _make_orchestrator()
            try:
                rows = sqlite3.connect(db).execute(
                    "SELECT class_name, status FROM idme_submissions ORDER BY id").fetchall()
                orch.get_submissions_for_date = MagicMock(return_value=[
                    {"class_name": c, "status": s} for c, s in rows])
                self.assertEqual(orch.classes_completed_on("2026-10-05"),
                                 {"5 USM", "5 UM"})
            finally:
                _stop(orch)


if __name__ == "__main__":
    unittest.main(verbosity=2)
