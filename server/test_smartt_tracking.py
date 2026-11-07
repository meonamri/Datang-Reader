"""
Unit tests for what Smartt records about its own outcomes.

Three gaps made the records weaker than they looked:
  * one failed getMe at startup disabled the bot until the next restart, so a
    brief Telegram error during a deploy would silently stop teacher prompts;
  * the "messages sent" count was intended sends, not accepted ones, so a prompt
    row proved nothing about delivery;
  * the portal status read after submit was dropped, so 'completed' could not be
    told apart from a day left as a draft when confirmation was requested.

Fake HTTP and a mocked portal - no network, no real token. Run directly
(`python test_smartt_tracking.py`) or under pytest.
"""

import asyncio
import logging
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import requests

from src.idme import telegram_bot as tb
from src.idme.migrations import apply_migrations
from src.idme.telegram_bot import IDMETelegramBot
from test_idme_full_attendance import _make_orchestrator, _stop

SCHEMA = Path(tb.__file__).with_name('schema.sql')
ACCEPTED = {'ok': True, 'result': {'message_id': 1}}
BAD_GATEWAY = {'ok': False, 'error_code': 502, 'description': 'Bad Gateway'}
UNAUTHORIZED = {'ok': False, 'error_code': 401, 'description': 'Unauthorized'}
TEACHER = {'id': 1, 'name': 'CIKGU', 'class_name': '5 UM', 'telegram_chat_id': '9'}


def reply(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


class FakeSession:
    """Answers by Bot API method; a list plays back one reply per call."""

    def __init__(self, **by_method):
        self.by_method = by_method
        self.calls = []

    def post(self, url, json=None, timeout=None):
        method = url.rsplit('/', 1)[-1]
        self.calls.append(method)
        step = self.by_method.get(method, ACCEPTED)
        if isinstance(step, list):
            step = step.pop(0)
        if isinstance(step, Exception):
            raise step
        return reply(step)


class BotTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = os.path.join(tmp.name, 'test.db')
        self.teachers = MagicMock()
        self.teachers.get_all_teachers.return_value = [TEACHER]
        self.teachers.get_teacher_for_class.return_value = TEACHER
        self.teachers.get_teacher.return_value = TEACHER
        self.detector = MagicMock()
        self.detector.detect_absences.return_value = [
            {'student_name': 'A', 'idpelajar': '1'},
            {'student_name': 'B', 'idpelajar': '2'},
        ]
        self.bot = IDMETelegramBot(
            'TOKEN', self.teachers, self.detector, MagicMock(), self.db)
        self.bot._poll_loop = MagicMock()

    def use(self, **by_method):
        session = FakeSession(**by_method)
        self.bot.client._session = session
        return session

    def sent_at(self):
        conn = sqlite3.connect(self.db)
        try:
            return dict(conn.execute(
                "SELECT student_name, sent_at FROM telegram_prompt_entries").fetchall())
        finally:
            conn.close()


class TestStartup(BotTestCase):
    def test_success_records_the_username(self):
        self.use(getMe={'ok': True, 'result': {'username': 'smartt_bot'}})
        self.assertTrue(self.bot.start())
        self.assertEqual(self.bot.bot_username, 'smartt_bot')

    def test_rejected_token_disables_the_bot(self):
        self.use(getMe=UNAUTHORIZED)
        self.assertFalse(self.bot.start())
        self.assertFalse(self.bot.running)

    def test_passing_failures_still_start_polling(self):
        for failure in (BAD_GATEWAY, requests.exceptions.ReadTimeout('t')):
            self.use(getMe=failure)
            self.assertTrue(self.bot.start())
            self.assertTrue(self.bot.running)


class TestPromptTracking(BotTestCase):
    SESSION = {'name': 'morning', 'forms': [5]}

    def prompt_session(self):
        with patch.object(tb.IDMEConfig, 'form_of', return_value=5):
            return self.bot.prompt_session(self.SESSION, '2026-11-08')

    def test_only_accepted_prompts_count(self):
        self.use(sendMessage=[ACCEPTED, ACCEPTED, BAD_GATEWAY])  # header, A, B
        with self.assertLogs(tb.__name__, level=logging.INFO) as logs:
            self.assertEqual(self.prompt_session(), 1)
        self.assertIn('1 messages sent, 1 failed', '\n'.join(logs.output))

    def test_sent_at_is_set_only_for_accepted_prompts(self):
        self.use(sendMessage=[ACCEPTED, ACCEPTED, BAD_GATEWAY])
        self.prompt_session()
        stamps = self.sent_at()
        self.assertIsNotNone(stamps['A'])
        self.assertIsNone(stamps['B'])

    def test_failed_prompt_is_not_resent(self):
        session = self.use(sendMessage=[ACCEPTED, BAD_GATEWAY, BAD_GATEWAY])
        self.prompt_session()
        self.assertEqual(session.calls.count('sendMessage'), 3)

    def test_failed_all_present_message_counts_as_failed(self):
        self.detector.detect_absences.return_value = []
        self.use(sendMessage=BAD_GATEWAY)
        self.assertEqual(self.prompt_session(), 0)

    def test_prompt_says_every_student_needs_an_answer(self):
        self.use()
        client = MagicMock(wraps=self.bot.client)
        self.bot.client = client
        self.prompt_session()
        header = client.send_message.call_args_list[0].args[1]
        self.assertIn('Semua pelajar perlu dijawab', header)
        self.assertNotIn('PONTENG', header)  # the gate blocks; nothing is defaulted

    def test_manual_prompt_reports_total_failure(self):
        self.use(sendMessage=BAD_GATEWAY)
        result = self.bot.prompt_class('5 UM', '2026-11-08')
        self.assertFalse(result['ok'])

    def test_manual_prompt_reports_partial_success(self):
        self.use(sendMessage=[ACCEPTED, ACCEPTED, BAD_GATEWAY])
        result = self.bot.prompt_class('5 UM', '2026-11-08')
        self.assertTrue(result['ok'])
        self.assertEqual(result['sent'], 1)

    def test_lost_entry_table_does_not_stop_prompts(self):
        self.use()
        self.bot._entries_conn = MagicMock(side_effect=sqlite3.OperationalError('locked'))
        self.assertEqual(self.prompt_session(), 2)


class TestMigrations(unittest.TestCase):
    OLD = """
        CREATE TABLE students (id INTEGER PRIMARY KEY);
        CREATE TABLE teachers (id INTEGER PRIMARY KEY);
        CREATE TABLE idme_submissions (id INTEGER PRIMARY KEY, status TEXT);
        CREATE TABLE telegram_prompt_entries (
            entry_id TEXT PRIMARY KEY, teacher_id INTEGER NOT NULL,
            class_name TEXT NOT NULL, student_name TEXT NOT NULL, idpelajar TEXT,
            scan_date DATE NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO idme_submissions (status) VALUES ('completed');
    """

    @staticmethod
    def columns(conn, table):
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}

    def test_existing_database_gains_columns_and_keeps_rows(self):
        conn = sqlite3.connect(':memory:')
        conn.executescript(self.OLD)
        apply_migrations(conn)
        apply_migrations(conn)  # safe on every startup
        self.assertLessEqual(
            {'portal_status', 'form_submitted', 'write_attempted'},
            self.columns(conn, 'idme_submissions'))
        self.assertIn('sent_at', self.columns(conn, 'telegram_prompt_entries'))
        self.assertEqual(
            conn.execute("SELECT status, portal_status FROM idme_submissions").fetchall(),
            [('completed', None)])

    def test_new_database_has_the_columns(self):
        conn = sqlite3.connect(':memory:')
        conn.executescript(SCHEMA.read_text())
        apply_migrations(conn)
        self.assertIn('portal_status', self.columns(conn, 'idme_submissions'))
        self.assertIn('sent_at', self.columns(conn, 'telegram_prompt_entries'))


class TestPortalEvidence(unittest.TestCase):
    def setUp(self):
        self.orch = _make_orchestrator()
        self.addCleanup(_stop, self.orch)

    def submit(self, fill_result, confirm):
        orch = self.orch
        orch.absence_detector.detect_absences.return_value = []
        orch.absence_detector.get_attendance_summary.return_value = {
            'roster_count': 2, 'scanned_count': 2}
        orch.teacher_manager.get_teacher_credentials.return_value = {
            'ic_number': 'x', 'password': 'y'}
        orch.roster_manager.upsert_from_portal.return_value = {
            'class_name': '5 UM', 'total': 2, 'added': 0, 'updated': 2,
            'renamed': [], 'removed': []}
        engine = MagicMock()
        engine.login_and_navigate = AsyncMock(return_value={
            'success': True, 'page': MagicMock(), 'cookies': [], 'csrf_token': 't'})
        engine.close = AsyncMock()
        filler = MagicMock()
        filler.get_student_list = AsyncMock(
            return_value=[{'id': str(i), 'name': f'S {i}'} for i in range(2)])
        filler.mark_absences_and_submit = AsyncMock(return_value=fill_result)
        with patch('src.idme.orchestrator.IDMELoginEngine', return_value=engine), \
             patch('src.idme.orchestrator.IDMEFormFiller', return_value=filler):
            return asyncio.run(orch._submit_class_async(
                1, '5 UM', '2026-11-08', confirm=confirm))

    def saved(self):
        calls = [c.kwargs for c in self.orch._update_submission.call_args_list
                 if 'portal_status' in c.kwargs]
        self.assertEqual(len(calls), 1)
        return calls[0]

    @staticmethod
    def fill(status, submitted=True, write_attempted=True):
        return {'total': 0, 'success': 0, 'skipped': 0, 'failed': 0, 'duration': 1.0,
                'submitted': submitted, 'status': status,
                'write_attempted': write_attempted}

    def test_confirmed_submit_saves_the_evidence_quietly(self):
        logger = logging.getLogger('src.idme.orchestrator')
        with patch.object(logger, 'warning') as warning:
            self.submit(self.fill('TELAH DISAHKAN'), confirm=True)
        saved = self.saved()
        self.assertEqual(saved['portal_status'], 'TELAH DISAHKAN')
        self.assertEqual(saved['form_submitted'], 1)
        self.assertEqual(saved['write_attempted'], 1)
        self.assertFalse(
            any('confirmation requested' in str(c) for c in warning.call_args_list))

    def test_draft_after_requested_confirmation_warns_and_stays_completed(self):
        with self.assertLogs('src.idme.orchestrator', level=logging.WARNING) as logs:
            result = self.submit(self.fill('MENUNGGU PENGESAHAN'), confirm=True)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.saved()['portal_status'], 'MENUNGGU PENGESAHAN')
        self.assertIn('confirmation requested', '\n'.join(logs.output))

    def test_requested_draft_does_not_warn(self):
        logger = logging.getLogger('src.idme.orchestrator')
        with patch.object(logger, 'warning') as warning:
            self.submit(self.fill('MENUNGGU PENGESAHAN'), confirm=False)
        self.assertFalse(
            any('confirmation requested' in str(c) for c in warning.call_args_list))

    def test_missing_write_flag_stays_unknown(self):
        fill = self.fill('TELAH DISAHKAN')
        del fill['write_attempted']
        self.submit(fill, confirm=True)
        self.assertIsNone(self.saved()['write_attempted'])

    def test_update_submission_writes_the_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, 'x.db')
            conn = sqlite3.connect(db)
            conn.executescript(SCHEMA.read_text())
            conn.execute("INSERT INTO idme_submissions (teacher_id, class_name, "
                         "submission_date) VALUES (1, '5 UM', '2026-11-08')")
            conn.commit()
            conn.close()
            orch = _make_orchestrator()
            self.addCleanup(_stop, orch)
            del orch._update_submission  # back to the real method
            orch.db_path = db
            orch._update_submission(1, status='completed', portal_status='TELAH DISAHKAN',
                                    form_submitted=1, write_attempted=0)
            conn = sqlite3.connect(db)
            row = conn.execute("SELECT portal_status, form_submitted, write_attempted "
                               "FROM idme_submissions").fetchone()
            conn.close()
            self.assertEqual(row, ('TELAH DISAHKAN', 1, 0))


if __name__ == '__main__':
    unittest.main()
