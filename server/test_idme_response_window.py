"""Recent-day teacher responses: 7-day window, persisted Telegram prompt buttons,
dated prompt text, recent-day auto-submit/resume, and the prompt endpoint's date."""
import sqlite3
import threading
import time
from datetime import date, timedelta

import pytest
from cryptography.fernet import Fernet

from src.idme.idme_config import IDMEConfig
from src.idme.telegram_bot import IDMETelegramBot

TODAY = date.today()


def iso(days_back):
    return (TODAY - timedelta(days=days_back)).isoformat()


def test_response_window_bounds():
    w = IDMEConfig.in_response_window
    n = IDMEConfig.RESPONSE_WINDOW_DAYS
    assert w(iso(0)) and w(iso(n))
    assert not w(iso(n + 1))
    assert not w(iso(-1))            # future
    assert not w('26/10/2026') and not w(None)


def _bot(db):
    return IDMETelegramBot('0:test', None, None, None, db)


def test_prompt_entries_survive_restart_with_their_own_date(tmp_path):
    db = str(tmp_path / 'idme.db')
    teacher = {'id': 5, 'class_name': '1 UKM'}
    first = _bot(db)
    recent = first._register_entry(teacher, {'student_name': 'A', 'idpelajar': 'x'}, iso(2))
    stale = first._register_entry(teacher, {'student_name': 'B'}, iso(IDMEConfig.RESPONSE_WINDOW_DAYS + 1))

    restarted = _bot(db)  # fresh process: empty in-memory registry
    entry = restarted._get_entry(recent)
    assert entry['scan_date'] == iso(2)
    assert entry['class_name'] == '1 UKM' and entry['teacher_id'] == 5
    assert restarted._get_entry(stale) is None      # outside window -> expired
    assert restarted._get_entry('unknown') is None
    assert restarted._get_entry('') is None


def test_out_of_window_entries_are_pruned(tmp_path):
    db = str(tmp_path / 'idme.db')
    bot = _bot(db)
    teacher = {'id': 1, 'class_name': '1 UKM'}
    old_day = iso(IDMEConfig.RESPONSE_WINDOW_DAYS + 1)
    bot._register_entry(teacher, {'student_name': 'OLD'}, old_day)
    bot._register_entry(teacher, {'student_name': 'NEW'}, iso(0))
    days = [r[0] for r in sqlite3.connect(db).execute(
        "SELECT scan_date FROM telegram_prompt_entries")]
    assert old_day not in days and iso(0) in days


def test_prompt_text_shows_date():
    text = IDMETelegramBot._prompt_text(
        {'student_name': 'A', 'class_name': '1 UKM', 'scan_date': '2026-10-30'})
    assert '30/10/2026' in text and '1 UKM' in text


@pytest.fixture
def orchestrator(tmp_path, monkeypatch):
    monkeypatch.setenv('IDME_ENCRYPTION_KEY', Fernet.generate_key().decode())
    from src.idme.orchestrator import IDMEOrchestrator
    return IDMEOrchestrator(db_path=str(tmp_path / 'o.db'))


def test_teacher_response_queues_only_days_in_window(orchestrator):
    o = orchestrator
    started = []
    o._auto_submit_if_ready = lambda c, d: started.append((c, d))
    o._latest_submission = lambda c, d: {'status': 'blocked'}
    o.handle_teacher_response('1 UKM', iso(1))
    o.handle_teacher_response('1 UKM', iso(IDMEConfig.RESPONSE_WINDOW_DAYS + 2))
    o.handle_teacher_response('1 UKM', iso(-1))
    time.sleep(0.3)
    assert started == [('1 UKM', iso(1))]


def test_resume_is_windowed_ordered_and_sequential(orchestrator):
    o = orchestrator
    rows = {
        iso(1): [{'class_name': 'A', 'status': 'blocked'},
                 {'class_name': 'B', 'status': 'blocked'},       # still unanswered
                 {'class_name': 'C', 'status': 'completed'}],
        iso(3): [{'class_name': 'A', 'status': 'blocked'},
                 {'class_name': 'A', 'status': 'failed'}],       # latest is failed
        iso(IDMEConfig.RESPONSE_WINDOW_DAYS + 2): [{'class_name': 'Z', 'status': 'blocked'}],
        iso(0): [{'class_name': 'D', 'status': 'blocked'}],
    }
    o.get_submissions_for_date = lambda d: rows.get(d, [])
    o._unanswered_absences = lambda c, d, a=None: ['x'] if c == 'B' else []
    assert o.ready_blocked_submissions() == [('A', iso(1)), ('D', iso(0))]

    order, live, peak, lock = [], [0], [0], threading.Lock()

    def fake_submit(c, d):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        order.append((c, d))
        with lock:
            live[0] -= 1
        with o._auto_retry_guard:
            o._auto_retry_inflight.discard((d, c))

    o._auto_submit_if_ready = fake_submit
    o.resume_ready_blocked_submissions()
    time.sleep(0.5)
    assert order == [('A', iso(1)), ('D', iso(0))]
    assert peak[0] == 1   # one Firefox at a time


def test_prompt_endpoint_date_validation():
    from flask import Flask
    from src.idme import api_routes as ar

    calls = []

    class FakeBot:
        def prompt_class(self, class_name, scan_date=None):
            calls.append((class_name, scan_date))
            return {'ok': True, 'sent': 1, 'teacher': 't'}

    saved = (ar._teacher_manager, ar._telegram_bot)
    ar._teacher_manager, ar._telegram_bot = object(), FakeBot()
    try:
        app = Flask('t')
        app.register_blueprint(ar.idme_bp)
        url = next(r.rule for r in app.url_map.iter_rules()
                   if r.rule.endswith('/telegram/prompt'))
        client = app.test_client()
        post = lambda body: client.post(url, json=body).status_code
        assert post({'class_name': '1 UKM'}) == 200
        assert post({'class_name': '1 UKM', 'date': iso(1)}) == 200
        assert post({'class_name': '1 UKM',
                     'date': iso(IDMEConfig.RESPONSE_WINDOW_DAYS + 1)}) == 400
        assert post({'class_name': '1 UKM', 'date': '01/11/2026'}) == 400
        assert post({'class_name': '1 UKM', 'date': iso(-1)}) == 400
        assert calls == [('1 UKM', None), ('1 UKM', iso(1))]
    finally:
        ar._teacher_manager, ar._telegram_bot = saved
