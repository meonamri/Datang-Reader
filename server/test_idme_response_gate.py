"""Regression tests for the teacher-response integrity gate."""

import asyncio
import logging
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.idme.absence_reason_store import AbsenceReasonStore
from src.idme.orchestrator import IDMEOrchestrator
from src.idme.migrations import apply_migrations
from src.idme.telegram_bot import IDMETelegramBot


_COMPONENTS = [
    "CredentialManager", "TeacherManager", "RosterManager", "ScanTracker",
    "PresentOverrideStore", "AbsenceDetector", "SessionCache",
]


def _make_orchestrator():
    patchers = [patch(f"src.idme.orchestrator.{name}") for name in _COMPONENTS]
    for item in patchers:
        item.start()
    orch = IDMEOrchestrator(db_path=":memory:")
    orch._create_submission_record = MagicMock(return_value=7)
    orch._update_submission = MagicMock()
    orch.reason_store = MagicMock()
    orch._patchers = patchers
    return orch


def _stop(orch):
    for item in orch._patchers:
        item.stop()


def _absence(name="AISYAH", student_id="42"):
    return {
        "student_name": name, "class_name": "5 UM", "idpelajar": student_id,
        "category": "N", "sebab_id": "N0040027",
    }


class ResponseReadinessTests(unittest.TestCase):
    def test_missing_reason_is_unanswered(self):
        orch = _make_orchestrator()
        try:
            orch.reason_store.get_reasons_for.return_value = {}
            self.assertEqual(
                orch._unanswered_absences("5 UM", "2026-09-17", [_absence()]),
                [_absence()],
            )
        finally:
            _stop(orch)

    def test_explicit_ponteng_reason_counts_as_answer(self):
        orch = _make_orchestrator()
        try:
            orch.reason_store.get_reasons_for.return_value = {
                AbsenceReasonStore.id_key("42"): {
                    "sebab_id": "N0040027", "category": "N"}
            }
            self.assertEqual(
                orch._unanswered_absences("5 UM", "2026-09-17", [_absence()]),
                [],
            )
        finally:
            _stop(orch)

    def test_name_fallback_counts_as_answer(self):
        orch = _make_orchestrator()
        try:
            row = _absence(student_id=None)
            orch.reason_store.get_reasons_for.return_value = {
                AbsenceReasonStore.name_key("AISYAH"): {
                    "sebab_id": "D0010075", "category": "D"}
            }
            self.assertEqual(
                orch._unanswered_absences("5 UM", "2026-09-17", [row]), [])
        finally:
            _stop(orch)

    def test_no_current_absences_needs_no_reason_query(self):
        orch = _make_orchestrator()
        try:
            self.assertEqual(
                orch._unanswered_absences("5 UM", "2026-09-17", []), [])
            orch.reason_store.get_reasons_for.assert_not_called()
        finally:
            _stop(orch)


class MigrationTests(unittest.TestCase):
    def test_existing_submission_table_gets_integrity_columns(self):
        db = Path(tempfile.mkdtemp()) / "idme.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE students (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE teachers (id INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE idme_submissions "
            "(id INTEGER PRIMARY KEY, class_name TEXT)")
        apply_migrations(conn)
        columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(idme_submissions)").fetchall()}
        conn.close()
        self.assertIn("unanswered_count", columns)
        self.assertIn("requested_confirm", columns)


class TelegramCallbackTests(unittest.TestCase):
    def test_durable_answer_calls_orchestrator_hook(self):
        bot = IDMETelegramBot.__new__(IDMETelegramBot)
        bot.response_callback = MagicMock()
        bot.logger = logging.getLogger(__name__)
        entry = {"class_name": "5 UM", "scan_date": "2026-09-17"}
        bot._notify_response_recorded(entry)
        bot.response_callback.assert_called_once_with("5 UM", "2026-09-17")


class SubmissionGateTests(unittest.TestCase):
    def test_unanswered_class_blocks_before_credentials_or_portal(self):
        orch = _make_orchestrator()
        try:
            orch.absence_detector.detect_absences.return_value = [_absence()]
            orch.absence_detector.get_attendance_summary.return_value = {
                "roster_count": 2, "scanned_count": 1}
            orch.reason_store.get_reasons_for.return_value = {}

            with patch("src.idme.orchestrator.IDMELoginEngine") as engine:
                result = asyncio.run(orch._submit_class_async(
                    1, "5 UM", "2026-09-17", confirm=True))

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["unanswered_count"], 1)
            self.assertFalse(result["form_submitted"])
            engine.assert_not_called()
            orch.teacher_manager.get_teacher_credentials.assert_not_called()
            orch._update_submission.assert_any_call(
                7, status="blocked", successful=0, failed=0,
                unanswered_count=1, duration=unittest.mock.ANY,
                error="Awaiting teacher response for 1 absent student")
        finally:
            _stop(orch)

    def test_blocked_notifier_runs_but_success_notifier_does_not(self):
        orch = _make_orchestrator()
        try:
            orch.blocked_notifier = MagicMock()
            orch.submission_notifier = MagicMock()
            result = {"status": "blocked", "unanswered_count": 2}
            orch._notify_submission("5 UM", result)
            orch.blocked_notifier.assert_called_once_with("5 UM", result)
            orch.submission_notifier.assert_not_called()
        finally:
            _stop(orch)

    def test_concurrent_same_class_submission_is_suppressed(self):
        orch = _make_orchestrator()
        try:
            key = ("2026-09-17", "5 UM")
            lock = threading.Lock()
            lock.acquire()
            orch._submission_locks[key] = lock
            result = orch.submit_class(1, "5 UM", key[0], confirm=True)
            self.assertEqual(result["status"], "running")
            orch._create_submission_record.assert_not_called()
        finally:
            lock.release()
            _stop(orch)


class AutoCatchupTests(unittest.TestCase):
    def test_ready_blocked_class_auto_submits_with_original_mode(self):
        orch = _make_orchestrator()
        try:
            today = date.today().isoformat()
            orch._latest_submission = MagicMock(return_value={
                "status": "blocked", "requested_confirm": 1})
            orch._unanswered_absences = MagicMock(return_value=[])
            orch.teacher_manager.get_teacher_for_class.return_value = {"id": 9}
            orch.submit_class = MagicMock(return_value={"status": "completed"})

            orch._auto_submit_if_ready("5 UM", today)

            orch.submit_class.assert_called_once_with(
                9, "5 UM", today, confirm=True)
        finally:
            _stop(orch)

    def test_response_burst_queues_only_one_worker(self):
        orch = _make_orchestrator()
        try:
            today = date.today().isoformat()
            orch._latest_submission = MagicMock(return_value={"status": "blocked"})
            with patch("src.idme.orchestrator.threading.Thread") as thread:
                orch.handle_teacher_response("5 UM", today)
                orch.handle_teacher_response("5 UM", today)
                thread.assert_called_once()
                thread.return_value.start.assert_called_once()
        finally:
            _stop(orch)

    def test_incomplete_or_previous_day_never_auto_submits(self):
        orch = _make_orchestrator()
        try:
            orch._latest_submission = MagicMock(return_value={
                "status": "blocked", "requested_confirm": 1})
            orch._unanswered_absences = MagicMock(return_value=[_absence()])
            orch.submit_class = MagicMock()
            orch._auto_submit_if_ready("5 UM", date.today().isoformat())
            orch.submit_class.assert_not_called()

            with patch("src.idme.orchestrator.threading.Thread") as thread:
                orch.handle_teacher_response("5 UM", "2020-01-01")
                thread.assert_not_called()
        finally:
            _stop(orch)


if __name__ == "__main__":
    unittest.main(verbosity=2)
