"""
Unit tests for the FULL-ATTENDANCE submission path (orchestrator.py + form_filler.py).

Bug (found 2026-08-26 in prod): a class where every student scanned was never
submitted at all. `_submit_class_async` short-circuited on an empty absence list
and returned 'completed' without ever logging in, so on MOEIS the day read as
"attendance never taken" rather than "everyone present".

Covered here:
  * zero absences + a real roster -> normal login/submit path runs, form_filler
    is called with an EMPTY absent list, and the untouched form IS submitted;
  * that submit failing -> 'failed' (not a silent 'completed');
  * an EMPTY roster -> never submitted, never logged into, 'failed' and NOT
    retryable (and specifically not 'skipped', which submit_all_classes reads as
    the school-wide non-school-day signal);
  * form_filler.mark_absences_and_submit([]) fires exactly one submit;
  * the post-submission teacher DM fires for an all-present day.

Pure logic - the Playwright login/fill layer is mocked. Run directly
(`python test_idme_full_attendance.py`) or under pytest. Requires the IDME deps
importable (run from `server/`, e.g. with .venv-idme).
"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.idme.orchestrator import IDMEOrchestrator  # noqa: E402
from src.idme.form_filler import IDMEFormFiller  # noqa: E402


_COMPONENTS = [
    "CredentialManager", "TeacherManager", "RosterManager",
    "ScanTracker", "AbsenceDetector", "SessionCache",
]


def _make_orchestrator():
    """Construct an orchestrator with every collaborator mocked."""
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


def _run_all_present(orch, roster_count, fill_result):
    """Drive `_submit_class_async` for a class with ZERO absences.

    Returns (result, engine, filler) so the caller can assert on whether the
    portal was touched at all.
    """
    orch.absence_detector.detect_absences.return_value = []
    orch.absence_detector.get_attendance_summary.return_value = {
        "roster_count": roster_count, "scanned_count": roster_count,
    }
    orch.teacher_manager.get_teacher_credentials.return_value = {
        "ic_number": "x", "password": "y",
    }

    engine = MagicMock()
    engine.login_and_navigate = AsyncMock(
        return_value={"success": True, "page": MagicMock(),
                      "cookies": [], "csrf_token": "t"}
    )
    engine.close = AsyncMock()

    filler = MagicMock()
    filler.mark_absences_and_submit = AsyncMock(return_value=fill_result)

    with patch("src.idme.orchestrator.IDMELoginEngine", return_value=engine), \
         patch("src.idme.orchestrator.IDMEFormFiller", return_value=filler):
        result = asyncio.run(
            orch._submit_class_async(1, "5 UM", "2026-08-26", confirm=False)
        )
    return result, engine, filler


# What form_filler returns for a clean full-attendance submit: nothing marked,
# nothing failed, but the form went out.
_FULL_ATTENDANCE_OK = {
    "total": 0, "success": 0, "skipped": 0, "failed": 0,
    "submitted": True, "status": "MENUNGGU PENGESAHAN",
    "duration": 1.0, "write_attempted": True,
}


class FullAttendanceSubmitTests(unittest.TestCase):
    """The regression: an all-present class must still reach the portal."""

    def test_all_present_class_is_submitted(self):
        orch = _make_orchestrator()
        try:
            result, engine, filler = _run_all_present(
                orch, roster_count=26, fill_result=_FULL_ATTENDANCE_OK)
        finally:
            _stop(orch)

        # It logged in and submitted - the whole point of the fix.
        engine.login_and_navigate.assert_awaited_once()
        filler.mark_absences_and_submit.assert_awaited_once()
        self.assertEqual(
            filler.mark_absences_and_submit.await_args.kwargs["absent_students"], [])

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["form_submitted"])
        self.assertEqual(result["absent_count"], 0)
        self.assertEqual(result["roster_count"], 26)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["message"], "All students present")

    def test_all_present_submit_failing_is_reported_failed(self):
        """The form never went out, so the day is NOT recorded. Never 'completed'."""
        orch = _make_orchestrator()
        try:
            result, _, _ = _run_all_present(orch, roster_count=26, fill_result={
                "total": 0, "success": 0, "skipped": 0, "failed": 0,
                "submitted": False, "status": "", "duration": 1.0,
                "write_attempted": False,
                "error": "Table not found: timeout",
            })
        finally:
            _stop(orch)

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["form_submitted"])
        # Nothing was written, so the run-level retry pass may take it.
        self.assertTrue(result["retryable"])

    def test_empty_roster_is_never_submitted(self):
        """An empty roster is not the same as everyone present: do not submit."""
        orch = _make_orchestrator()
        try:
            result, engine, filler = _run_all_present(
                orch, roster_count=0, fill_result=_FULL_ATTENDANCE_OK)
        finally:
            _stop(orch)

        engine.login_and_navigate.assert_not_awaited()
        filler.mark_absences_and_submit.assert_not_awaited()

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["retryable"])
        self.assertFalse(result["form_submitted"])
        # NOT 'skipped': submit_all_classes treats that as a school-wide
        # non-school day and would abandon every remaining class.
        self.assertNotEqual(result["status"], "skipped")

    def test_all_present_notifies_the_teacher(self):
        """The class WAS recorded to IDME, so the teacher DM should fire."""
        orch = _make_orchestrator()
        orch.submission_notifier = MagicMock()
        try:
            orch._notify_submission("5 UM", {
                "status": "completed", "form_submitted": True, "submitted": 0,
                "absent_count": 0,
            })
            orch.submission_notifier.assert_called_once()
        finally:
            _stop(orch)

    def test_failed_all_present_does_not_notify(self):
        orch = _make_orchestrator()
        orch.submission_notifier = MagicMock()
        try:
            orch._notify_submission("5 UM", {
                "status": "failed", "form_submitted": False, "submitted": 0,
                "absent_count": 0,
            })
            orch.submission_notifier.assert_not_called()
        finally:
            _stop(orch)


class FormFillerEmptyListTests(unittest.TestCase):
    """`mark_absences_and_submit([])` must submit, not skip."""

    def _filler(self):
        page = MagicMock()
        page.wait_for_selector = AsyncMock()
        filler = IDMEFormFiller(page, debug=False)
        filler._take_screenshot = AsyncMock()
        filler._submit_form = AsyncMock(return_value="MENUNGGU PENGESAHAN")
        return filler

    def test_empty_list_submits_untouched_form(self):
        filler = self._filler()
        result = asyncio.run(filler.mark_absences_and_submit([], confirm=False))

        filler._submit_form.assert_awaited_once_with(confirm=False)
        self.assertTrue(result["submitted"])
        self.assertEqual(result["status"], "MENUNGGU PENGESAHAN")
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["success"], 0)
        self.assertEqual(result["failed"], 0)

    def test_empty_list_with_unloadable_table_does_not_submit(self):
        """No student table means we never saw the class: do not blind-submit."""
        filler = self._filler()
        filler.page.wait_for_selector = AsyncMock(side_effect=Exception("timeout"))

        result = asyncio.run(filler.mark_absences_and_submit([], confirm=False))

        filler._submit_form.assert_not_awaited()
        self.assertFalse(result["submitted"])
        self.assertFalse(result["write_attempted"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
