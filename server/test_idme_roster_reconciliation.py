"""Regression tests for automated roster reconciliation and fail-closed writes."""

import asyncio
import logging
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.idme.form_filler import IDMEFormFiller
from src.idme.migrations import apply_migrations
from src.idme.orchestrator import IDMEOrchestrator
from src.idme.telegram_bot import TelegramPromptScheduler


def _absence(name="AISYAH", student_id="42"):
    return {
        "student_name": name,
        "class_name": "5 UM",
        "idpelajar": student_id,
        "category": "N",
        "sebab_id": "N0040027",
    }


class FailClosedFormTests(unittest.TestCase):
    def _filler(self):
        filler = IDMEFormFiller.__new__(IDMEFormFiller)
        filler.page = MagicMock()
        filler.page.wait_for_selector = AsyncMock()
        filler.debug = False
        filler.logger = logging.getLogger(__name__)
        filler.write_attempted = False
        filler._take_screenshot = AsyncMock()
        filler._submit_form = AsyncMock(return_value="TELAH DISAHKAN")
        return filler

    def test_roster_mismatch_writes_nothing(self):
        filler = self._filler()
        filler.validate_student_matches = AsyncMock(return_value=["AISYAH"])
        filler.mark_student_absent = AsyncMock(return_value="marked")

        result = asyncio.run(filler.mark_absences_and_submit([_absence()]))

        self.assertEqual(result["error_code"], "roster_mismatch")
        self.assertFalse(result["write_attempted"])
        filler.mark_student_absent.assert_not_called()
        filler._submit_form.assert_not_called()

    def test_marking_failure_cannot_submit_successful_subset(self):
        filler = self._filler()
        filler.validate_student_matches = AsyncMock(return_value=[])
        filler.mark_student_absent = AsyncMock(
            side_effect=["marked", "failed"])

        result = asyncio.run(filler.mark_absences_and_submit([
            _absence("AISYAH", "42"), _absence("BALQIS", "43")]))

        self.assertEqual(result["failed"], 1)
        self.assertFalse(result["submitted"])
        self.assertFalse(result["write_attempted"])
        filler._submit_form.assert_not_called()


class RosterSyncSchemaTests(unittest.TestCase):
    def test_roster_sync_table_is_created(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            conn = sqlite3.connect(tmp.name)
            conn.executescript("""
                CREATE TABLE students (id INTEGER PRIMARY KEY);
                CREATE TABLE teachers (id INTEGER PRIMARY KEY);
                CREATE TABLE idme_submissions (id INTEGER PRIMARY KEY);
            """)
            apply_migrations(conn)
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")
            }
            self.assertIn("roster_sync_runs", tables)
            conn.close()


class SessionRefreshTests(unittest.TestCase):
    def _orchestrator(self):
        orch = IDMEOrchestrator.__new__(IDMEOrchestrator)
        orch.logger = logging.getLogger(__name__)
        orch._roster_sync_lock = threading.Lock()
        orch.roster_sync_notifier = MagicMock()
        orch.teacher_manager = MagicMock()
        orch.teacher_manager.get_all_teachers.return_value = [
            {"id": 1, "class_name": "5 UM"},
            {"id": 2, "class_name": "1 UM"},
        ]
        orch.init_roster_from_portal = MagicMock(return_value={
            "total": 20, "added": 0, "renamed": [], "removed": [],
            "roster_state": "current",
        })
        return orch

    def test_refresh_is_scoped_to_session_forms(self):
        orch = self._orchestrator()
        orch.get_roster_sync_status = MagicMock(return_value={})

        result = orch.refresh_session_rosters(
            {"name": "morning", "forms": [3, 4, 5, 6]},
            sync_date="2026-09-22")

        self.assertEqual(result["attempted"], 1)
        orch.init_roster_from_portal.assert_called_once_with(
            1, "5 UM", trigger="pre_prompt", sync_date="2026-09-22")

    def test_cutoff_retry_selects_only_failed_or_missing(self):
        orch = self._orchestrator()
        orch.teacher_manager.get_all_teachers.return_value.append(
            {"id": 3, "class_name": "3 UM"})
        orch.get_roster_sync_status = MagicMock(return_value={
            "5 UM": {"status": "current"},
            "3 UM": {"status": "failed"},
        })

        result = orch.refresh_session_rosters(
            {"name": "cutoff", "forms": [3, 4, 5, 6]},
            sync_date="2026-09-22", trigger="cutoff_retry",
            only_stale=True)

        self.assertEqual(result["attempted"], 1)
        orch.init_roster_from_portal.assert_called_once_with(
            3, "3 UM", trigger="cutoff_retry", sync_date="2026-09-22")


class PromptRefreshSchedulerTests(unittest.TestCase):
    def test_pre_prompt_timer_runs_refresh_when_school_day(self):
        refresh = MagicMock()
        scheduler = TelegramPromptScheduler(
            MagicMock(),
            [{"name": "morning", "forms": [3, 4, 5, 6],
              "prompt_time": "10:00"}],
            roster_refresh=refresh,
        )
        scheduler._should_prompt = MagicMock(return_value=(True, "school day"))
        scheduler.running = False

        scheduler._execute_roster_refresh(scheduler.sessions[0])

        refresh.assert_called_once()
        self.assertEqual(refresh.call_args.kwargs["trigger"], "pre_prompt")

    def test_prompt_recovery_only_fills_missing_attempts(self):
        bot = MagicMock()
        refresh = MagicMock()
        scheduler = TelegramPromptScheduler(
            bot,
            [{"name": "morning", "forms": [3, 4, 5, 6],
              "prompt_time": "10:00"}],
            roster_refresh=refresh,
        )
        scheduler._should_prompt = MagicMock(return_value=(True, "school day"))
        scheduler.running = False

        scheduler._execute(scheduler.sessions[0])

        self.assertTrue(refresh.call_args.kwargs["only_missing"])
        self.assertEqual(refresh.call_args.kwargs["trigger"], "prompt_recovery")
        bot.prompt_session.assert_called_once()

    def test_refresh_failure_does_not_swallow_prompt(self):
        bot = MagicMock()
        scheduler = TelegramPromptScheduler(
            bot,
            [{"name": "morning", "forms": [3, 4, 5, 6],
              "prompt_time": "10:00"}],
            roster_refresh=MagicMock(side_effect=RuntimeError("portal down")),
        )
        scheduler._should_prompt = MagicMock(return_value=(True, "school day"))
        scheduler.running = False

        scheduler._execute(scheduler.sessions[0])

        bot.prompt_session.assert_called_once()


class SubmissionRosterPreflightTests(unittest.TestCase):
    def test_new_unanswered_pupil_blocks_before_form_write(self):
        component_names = [
            "CredentialManager", "TeacherManager", "RosterManager",
            "ScanTracker", "PresentOverrideStore", "AbsenceDetector",
            "SessionCache",
        ]
        patchers = [
            patch(f"src.idme.orchestrator.{name}") for name in component_names]
        for item in patchers:
            item.start()
        try:
            orch = IDMEOrchestrator(db_path=":memory:")
            orch._create_submission_record = MagicMock(return_value=8)
            orch._update_submission = MagicMock()
            orch.get_roster_sync_status = MagicMock(return_value={})
            first = _absence("AISYAH", "42")
            added = _absence("BALQIS", "43")
            orch.absence_detector.detect_absences.side_effect = [
                [first], [first, added]]
            orch.absence_detector.get_attendance_summary.side_effect = [
                {"roster_count": 1, "scanned_count": 0},
                {"roster_count": 2, "scanned_count": 0},
            ]
            orch._unanswered_absences = MagicMock(
                side_effect=[[], [added]])
            orch.teacher_manager.get_teacher_credentials.return_value = {
                "ic_number": "x", "password": "y"}
            orch.roster_manager.upsert_from_portal.return_value = {
                "class_name": "5 UM", "total": 2, "added": 1,
                "updated": 1, "renamed": [], "removed": [],
            }

            engine = MagicMock()
            engine.login_and_navigate = AsyncMock(return_value={
                "success": True, "page": MagicMock(), "cookies": [],
                "csrf_token": "t"})
            engine.close = AsyncMock()
            filler = MagicMock()
            filler.get_student_list = AsyncMock(return_value=[
                {"id": "42", "name": "AISYAH"},
                {"id": "43", "name": "BALQIS"},
            ])
            filler.mark_absences_and_submit = AsyncMock()

            with patch(
                "src.idme.orchestrator.IDMELoginEngine", return_value=engine
            ), patch(
                "src.idme.orchestrator.IDMEFormFiller", return_value=filler
            ):
                result = asyncio.run(orch._submit_class_async(
                    1, "5 UM", "2026-09-22", confirm=True))

            self.assertEqual(result["status"], "blocked")
            self.assertTrue(result["roster_changed"])
            self.assertEqual(result["unanswered_count"], 1)
            self.assertFalse(result["write_attempted"])
            filler.mark_absences_and_submit.assert_not_awaited()
        finally:
            for item in patchers:
                item.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
