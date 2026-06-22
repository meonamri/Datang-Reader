"""
Unit tests for the IDME submission retry path (orchestrator.py).

Covers the two behaviours added to recover from transient, pre-submission portal
failures (a slow AJAX student-table load; an SSO bounce to the app picker) seen in
prod on 2026-06-22 (5 UM, 2 UM):

  * `_submit_class_async` tags a failure `retryable` ONLY when the submit AJAX was
    never fired (form_filler `write_attempted=False`) — a post-write failure must
    never be auto-retried (double-submit risk once SCHEDULER_CONFIRM=true).
  * `submit_all_classes` runs one run-level retry pass over retryable failures,
    leaves post-write failures / skips alone, and is suppressed on a non-school day.

Pure logic — the Playwright login/fill layer is mocked. Run directly
(`python test_idme_retry.py`) or under pytest. Requires the IDME deps importable
(run from `server/`, e.g. with .venv-idme).
"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.idme.orchestrator import IDMEOrchestrator, OrchestratorError  # noqa: E402
from src.idme.login_engine import LoginEngineError  # noqa: E402


# Component classes patched out so IDMEOrchestrator() builds without a real DB,
# Fernet key, or network.
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
    # DB writes are not under test — make them no-ops.
    orch._create_submission_record = MagicMock(return_value=1)
    orch._update_submission = MagicMock()
    orch._record_skip = MagicMock()
    orch._patchers = patchers  # keep refs alive for stop()
    return orch


def _stop(orch):
    for p in orch._patchers:
        p.stop()


class RetryableFlagTests(unittest.TestCase):
    """`_submit_class_async` — does a failure get marked retryable correctly?"""

    def _run_with_fill_result(self, fill_result):
        orch = _make_orchestrator()
        try:
            orch.absence_detector.detect_absences.return_value = [
                {"student_name": "A", "category": "N", "sebab_id": "N0040027"}
            ]
            orch.absence_detector.get_attendance_summary.return_value = {
                "roster_count": 1, "scanned_count": 0,
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
                return asyncio.run(
                    orch._submit_class_async(1, "5 UM", "2026-06-22", confirm=False)
                )
        finally:
            _stop(orch)

    def test_pre_write_failure_is_retryable(self):
        """Table never loaded: submitted=False, write_attempted=False -> retryable."""
        result = self._run_with_fill_result({
            "total": 1, "success": 0, "failed": 1, "submitted": False,
            "status": "", "duration": 1.0, "write_attempted": False,
            "error": "Table not found: timeout",
        })
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["retryable"])

    def test_post_write_failure_is_not_retryable(self):
        """Submit AJAX fired but status read failed -> must NOT be retried."""
        result = self._run_with_fill_result({
            "total": 1, "success": 1, "failed": 0, "submitted": False,
            "status": "", "duration": 1.0, "write_attempted": True,
        })
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["retryable"])

    def test_success_is_not_retryable(self):
        result = self._run_with_fill_result({
            "total": 1, "success": 1, "failed": 0, "submitted": True,
            "status": "MENUNGGU PENGESAHAN", "duration": 1.0,
            "write_attempted": True,
        })
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["retryable"])


class RetryPassTests(unittest.TestCase):
    """`submit_all_classes` — the run-level retry pass."""

    def _orchestrator_with_classes(self, classes):
        orch = _make_orchestrator()
        orch.teacher_manager.get_all_teachers.return_value = [
            {"id": tid, "name": f"T{tid}", "class_name": cn}
            for tid, cn in classes
        ]
        return orch

    def test_retryable_failure_is_retried_and_can_succeed(self):
        orch = self._orchestrator_with_classes([(1, "5 UM")])
        try:
            first = {"class_name": "5 UM", "status": "failed", "retryable": True}
            second = {"class_name": "5 UM", "status": "completed", "retryable": False}
            orch.submit_class = MagicMock(side_effect=[first, second])
            with patch("src.idme.orchestrator.time.sleep"):
                results = orch.submit_all_classes("2026-06-22", confirm=False)
            self.assertEqual(orch.submit_class.call_count, 2)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["status"], "completed")
        finally:
            _stop(orch)

    def test_post_write_failure_is_not_retried(self):
        orch = self._orchestrator_with_classes([(1, "2 UM")])
        try:
            failed = {"class_name": "2 UM", "status": "failed", "retryable": False}
            orch.submit_class = MagicMock(return_value=failed)
            with patch("src.idme.orchestrator.time.sleep"):
                results = orch.submit_all_classes("2026-06-22", confirm=False)
            self.assertEqual(orch.submit_class.call_count, 1)
            self.assertEqual(results[0]["status"], "failed")
        finally:
            _stop(orch)

    def test_skipped_class_is_not_retried(self):
        # A single class that comes back 'skipped' (non-school day). The pass must
        # not retry it AND must be suppressed wholesale by the non_school_day flag.
        orch = self._orchestrator_with_classes([(1, "5 UM")])
        try:
            skipped = {"class_name": "5 UM", "status": "skipped",
                       "message": "Non-school day"}
            orch.submit_class = MagicMock(return_value=skipped)
            with patch("src.idme.orchestrator.time.sleep"):
                results = orch.submit_all_classes("2026-06-22", confirm=False)
            self.assertEqual(orch.submit_class.call_count, 1)
            self.assertEqual(results[0]["status"], "skipped")
        finally:
            _stop(orch)

    def test_non_school_day_suppresses_retry_of_earlier_failure(self):
        # First class fails (retryable), second reports the holiday banner ->
        # non_school_day short-circuits. The retry pass must NOT fire, so the
        # first class's submit_class is called exactly once.
        orch = self._orchestrator_with_classes([(1, "5 UM"), (2, "3 UM")])
        try:
            results_seq = [
                {"class_name": "5 UM", "status": "failed", "retryable": True},
                {"class_name": "3 UM", "status": "skipped",
                 "message": "Non-school day"},
            ]
            orch.submit_class = MagicMock(side_effect=results_seq)
            with patch("src.idme.orchestrator.time.sleep"):
                results = orch.submit_all_classes("2026-06-22", confirm=False)
            # Two original calls, no retry of 5 UM.
            self.assertEqual(orch.submit_class.call_count, 2)
            statuses = {r["class_name"]: r["status"] for r in results}
            self.assertEqual(statuses["5 UM"], "failed")
            self.assertEqual(statuses["3 UM"], "skipped")
        finally:
            _stop(orch)

    def test_retry_is_bounded_to_one_attempt(self):
        orch = self._orchestrator_with_classes([(1, "5 UM")])
        try:
            # Fails both times, retryable both times — must still stop after one retry.
            failed = {"class_name": "5 UM", "status": "failed", "retryable": True}
            orch.submit_class = MagicMock(return_value=failed)
            with patch("src.idme.orchestrator.time.sleep"):
                results = orch.submit_all_classes("2026-06-22", confirm=False)
            self.assertEqual(orch.submit_class.call_count, 2)  # original + 1 retry
            self.assertEqual(results[0]["status"], "failed")
        finally:
            _stop(orch)

    def test_login_exception_becomes_retryable_failure(self):
        # An exception out of submit_class (e.g. the new not-on-MOEIS
        # LoginEngineError) must be recorded retryable and retried once.
        orch = self._orchestrator_with_classes([(1, "2 UM")])
        try:
            orch.submit_class = MagicMock(side_effect=[
                OrchestratorError("Submission failed: Not on MOEIS after SSO"),
                {"class_name": "2 UM", "status": "completed", "retryable": False},
            ])
            with patch("src.idme.orchestrator.time.sleep"):
                results = orch.submit_all_classes("2026-06-22", confirm=False)
            self.assertEqual(orch.submit_class.call_count, 2)
            self.assertEqual(results[0]["status"], "completed")
        finally:
            _stop(orch)


if __name__ == "__main__":
    unittest.main(verbosity=2)
