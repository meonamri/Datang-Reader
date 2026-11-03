"""Immediate submission once answers are complete, prompt-time submission of
all-present classes, cutoff as reminder/catch-up only, and the 3-hourly
same-month retry of portal failures."""
import asyncio
import threading
import time
from datetime import date, timedelta

import pytest
from cryptography.fernet import Fernet

from src.idme.idme_config import IDMEConfig

TODAY = date.today()


def iso(days_back):
    return (TODAY - timedelta(days=days_back)).isoformat()


@pytest.fixture
def orch(tmp_path, monkeypatch):
    monkeypatch.setenv('IDME_ENCRYPTION_KEY', Fernet.generate_key().decode())
    from src.idme.orchestrator import IDMEOrchestrator
    return IDMEOrchestrator(db_path=str(tmp_path / 'o.db'))


# ---- immediate submission ------------------------------------------------

def test_answer_completing_a_day_with_no_row_submits_immediately(orch):
    calls = []
    orch._latest_submission = lambda c, d: None              # before cutoff
    orch._unanswered_absences = lambda c, d, a=None: []
    orch.teacher_manager.get_teacher_for_class = lambda c: {'id': 7}
    orch.submit_class = lambda tid, c, d, confirm: calls.append((tid, c, d, confirm)) or {}
    orch.handle_teacher_response('1 UKM', iso(0))
    time.sleep(0.3)
    assert calls == [(7, '1 UKM', iso(0), IDMEConfig.SCHEDULER_CONFIRM)]


def test_answer_with_unanswered_left_or_already_completed_does_nothing(orch):
    calls = []
    orch.teacher_manager.get_teacher_for_class = lambda c: {'id': 7}
    orch.submit_class = lambda *a, **k: calls.append(a) or {}
    orch._latest_submission = lambda c, d: None
    orch._unanswered_absences = lambda c, d, a=None: ['still owed']
    orch.handle_teacher_response('1 UKM', iso(0))
    orch._latest_submission = lambda c, d: {'status': 'completed'}
    orch._unanswered_absences = lambda c, d, a=None: []
    orch.handle_teacher_response('1 UKM', iso(0))
    time.sleep(0.3)
    assert calls == []


def test_blocked_day_keeps_its_requested_confirm_mode(orch):
    calls = []
    orch._latest_submission = lambda c, d: {'status': 'blocked', 'requested_confirm': 0}
    orch._unanswered_absences = lambda c, d, a=None: []
    orch.teacher_manager.get_teacher_for_class = lambda c: {'id': 3}
    orch.submit_class = lambda tid, c, d, confirm: calls.append(confirm) or {}
    orch.handle_teacher_response('2 USM', iso(1))
    time.sleep(0.3)
    assert calls == [False]


# ---- prompt-time submission -------------------------------------------------

def test_prompt_time_submits_only_ready_unsubmitted_classes_in_session(orch, monkeypatch):
    monkeypatch.setattr(IDMEConfig, 'form_of', classmethod(lambda cls, c: int(c[0])))
    orch.teacher_manager.get_all_teachers = lambda: [
        {'id': 1, 'class_name': '1 UKM'},   # all present -> submit
        {'id': 2, 'class_name': '1 UM'},    # unanswered -> wait
        {'id': 3, 'class_name': '1 USM'},   # already has a row today -> skip
        {'id': 4, 'class_name': '1 KAA'},   # no roster -> skip
        {'id': 5, 'class_name': '3 UKM'},   # other session -> skip
    ]
    orch._latest_submission = lambda c, d: {'status': 'completed'} if c == '1 USM' else None
    orch.absence_detector.get_attendance_summary = (
        lambda c, d: {'roster_count': 0 if c == '1 KAA' else 25})
    orch._unanswered_absences = lambda c, d, a=None: ['x'] if c == '1 UM' else []
    started = []
    orch._resume_sequential = lambda pending: started.extend(pending)
    orch.submit_ready_classes({'name': 'evening', 'forms': [1, 2]}, iso(0))
    time.sleep(0.3)
    assert started == [('1 UKM', iso(0))]


def test_prompt_scheduler_calls_on_prompted_only_on_school_days():
    from src.idme.telegram_bot import TelegramPromptScheduler

    class Bot:
        def prompt_session(self, session):
            pass

    got = []
    s = TelegramPromptScheduler(Bot(), [{'name': 'evening', 'forms': [1, 2],
                                         'prompt_time': '14:00', 'cutoff': '16:00'}],
                                on_prompted=lambda sess, d: got.append((sess['name'], d)))
    ps = s.sessions[0]
    s._should_prompt = lambda today: (True, 'test')
    s._execute(ps)
    s._should_prompt = lambda today: (False, 'weekend')
    s._execute(ps)
    assert got == [('evening', TODAY.isoformat())]


# ---- cutoff ------------------------------------------------------------------

def test_cutoff_never_retouches_a_class_completed_today():
    from src.idme.scheduler import IDMEScheduler

    seen = {}

    class Orch:
        def classes_completed_on(self, day):
            return {'1 UKM'}

        def submit_all_classes(self, **kw):
            seen.update(kw)
            return []

    sch = IDMEScheduler(Orch(), [{'name': 'evening', 'cutoff': '16:00', 'forms': [1, 2]}])
    sch.running = False   # don't re-arm a real timer
    sch._execute(sch.sessions[0])
    assert seen['exclude_classes'] == {'1 UKM'} and seen['enforce_scan_gate'] is True


# ---- retry -------------------------------------------------------------------

@pytest.mark.parametrize('error,expected', [
    ('Page.wait_for_selector: Timeout 10000ms exceeded.\nCall log:\n  - waiting for '
     'locator("input[placeholder*=\\"Kad Pengenalan\\"], #ic") to be visible', True),
    ('Page.goto: Timeout 30000ms exceeded.', True),
    ('Not on MOEIS after SSO (landed on https://idme.moe.gov.my/list_aplikasi)', True),
    ('Student table reload for 26/10/2026 returned HTTP 502', True),
    ('Wrong password: Kata laluan salah', False),
    ('Login timed out after 30 seconds', False),
    ('Attendance for 26/10/2026 is already confirmed (TELAH DISAHKAN); locked days '
     'are not edited by automation', False),
    ("Portal served attendance for '2026-10-29', not requested '2026-10-30'", False),
    ('No roster for 4 UKM — initialise the roster before it can be submitted', False),
    ('Awaiting teacher response for 9 absent students', False),
    ('', False), (None, False),
])
def test_transient_failure_classification(orch, error, expected):
    assert orch.is_transient_failure(error) is expected


def test_retry_window_is_current_month_only():
    t = date(2026, 11, 2)
    w = IDMEConfig.in_retry_window
    assert w('2026-11-01', t) and w('2026-11-02', t)
    assert not w('2026-10-31', t) and not w('2026-11-03', t) and not w('x', t)


def test_retry_candidates_and_sequential_retry(orch):
    first = TODAY.replace(day=1)
    rows = {
        first.isoformat(): [
            {'class_name': 'A', 'status': 'failed', 'requested_confirm': 1,
             'error_message': 'Page.goto: Timeout 30000ms exceeded.'},
            {'class_name': 'B', 'status': 'failed', 'requested_confirm': 1,
             'error_message': 'Wrong password: Kata laluan salah'},
            {'class_name': 'C', 'status': 'failed', 'requested_confirm': 0,
             'error_message': 'Not on MOEIS after SSO'},
            {'class_name': 'C', 'status': 'completed'},          # latest wins
        ],
        (first - timedelta(days=1)).isoformat(): [               # last month
            {'class_name': 'Z', 'status': 'failed',
             'error_message': 'Page.goto: Timeout 30000ms exceeded.'}],
    }
    orch.get_submissions_for_date = lambda d: rows.get(d, [])
    assert orch.failed_retry_candidates() == [('A', first.isoformat(), True)]

    live, peak, calls, lock = [0], [0], [], threading.Lock()

    def fake_submit(tid, c, d, confirm):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        calls.append((c, d, confirm))
        with lock:
            live[0] -= 1
        return {'status': 'completed'}

    rows[first.isoformat()].append({'class_name': 'D', 'status': 'failed',
                                    'requested_confirm': None,
                                    'error_message': 'net::ERR_CONNECTION_RESET'})
    orch.teacher_manager.get_teacher_for_class = lambda c: {'id': 1}
    orch.submit_class = fake_submit
    orch.retry_failed_submissions()
    assert [c for c, _, _ in calls] == ['A', 'D'] and peak[0] == 1
    assert calls[1][2] == IDMEConfig.SCHEDULER_CONFIRM


def test_overlapping_retry_tick_is_skipped(orch):
    orch._retry_run_lock.acquire()
    try:
        orch.failed_retry_candidates = lambda: pytest.fail('should not run')
        assert orch.retry_failed_submissions() == []
    finally:
        orch._retry_run_lock.release()


# ---- one portal browser at a time --------------------------------------------

def test_submissions_never_drive_two_browsers_at_once(orch):
    live, peak, lock = [0], [0], threading.Lock()

    async def fake_async(tid, c, d, confirm):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        await asyncio.sleep(0.1)
        with lock:
            live[0] -= 1
        return {'status': 'completed', 'class_name': c}

    orch._submit_class_async = fake_async
    orch._notify_submission = lambda c, r: None
    ts = [threading.Thread(target=orch.submit_class, args=(1, c, iso(0), True))
          for c in ('A', 'B', 'C')]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert peak[0] == 1


# ---- teacher notifications ------------------------------------------------------

def test_blocked_reminder_sent_once_per_class_per_day_success_always(orch):
    sent = []
    orch.blocked_notifier = lambda c, r: sent.append(('blocked', c))
    orch.submission_notifier = lambda c, r: sent.append(('done', c))
    rows = [{'class_name': '1 UKM', 'status': 'blocked'}]
    orch.get_submissions_for_date = lambda d: rows
    blocked = {'status': 'blocked', 'date': iso(1)}
    orch._notify_submission('1 UKM', blocked)            # first block -> remind
    rows.append({'class_name': '1 UKM', 'status': 'failed'})
    rows.append({'class_name': '1 UKM', 'status': 'blocked'})
    orch._notify_submission('1 UKM', blocked)            # retry blocks again -> silent
    orch._notify_submission('1 UKM', {'status': 'completed', 'form_submitted': True,
                                      'date': iso(1)})   # success -> always
    assert sent == [('blocked', '1 UKM'), ('done', '1 UKM')]


def test_teacher_messages_name_the_day():
    from src.idme.telegram_bot import _for_day
    assert _for_day({'date': '2026-11-01'}) == ' bagi 01/11/2026'
    assert _for_day({}) == '' and _for_day(None) == ''


# ---- unlinked teachers are never submitted automatically ---------------------
# With the Telegram bot on, only classes whose teacher is linked are submitted
# by an automatic path; unlinked classes wait for "Submit remaining" / manual.

def test_prompt_time_leaves_unlinked_classes_for_manual_submit(orch, monkeypatch):
    monkeypatch.setattr(IDMEConfig, 'TELEGRAM_ENABLED', True)
    monkeypatch.setattr(IDMEConfig, 'form_of', classmethod(lambda cls, c: int(c[0])))
    orch.teacher_manager.get_all_teachers = lambda: [
        {'id': 1, 'class_name': '1 UKM', 'telegram_chat_id': 111},   # linked
        {'id': 2, 'class_name': '1 UM', 'telegram_chat_id': None},   # unlinked
    ]
    orch._latest_submission = lambda c, d: None
    orch.absence_detector.get_attendance_summary = lambda c, d: {'roster_count': 25}
    orch._unanswered_absences = lambda c, d, a=None: []
    started = []
    orch._resume_sequential = lambda pending: started.extend(pending)
    orch.submit_ready_classes({'name': 'evening', 'forms': [1, 2]}, iso(0))
    time.sleep(0.3)
    assert started == [('1 UKM', iso(0))]


def test_ready_check_never_auto_submits_an_unlinked_class(orch, monkeypatch):
    monkeypatch.setattr(IDMEConfig, 'TELEGRAM_ENABLED', True)
    calls = []
    orch._latest_submission = lambda c, d: {'status': 'blocked'}
    orch._unanswered_absences = lambda c, d, a=None: []
    orch.teacher_manager.get_teacher_for_class = lambda c: {'id': 7, 'telegram_chat_id': None}
    orch.submit_class = lambda *a, **k: calls.append(a) or {}
    orch._auto_submit_if_ready('1 UKM', iso(0))   # e.g. restart resume
    assert calls == []
    assert ('1 UKM', iso(0)) not in {(c, d) for d, c in orch._auto_retry_inflight}


def _cutoff_setup(orch, monkeypatch, telegram):
    monkeypatch.setattr(IDMEConfig, 'TELEGRAM_ENABLED', telegram)
    orch.teacher_manager.get_all_teachers = lambda: [
        {'id': 1, 'name': 'A', 'class_name': '3 UKM', 'telegram_chat_id': 111},
        {'id': 2, 'name': 'B', 'class_name': '3 UM', 'telegram_chat_id': None},
    ]
    submitted = []
    orch.submit_class = lambda tid, c, d, confirm: (
        submitted.append(c) or {'class_name': c, 'status': 'completed'})
    return submitted


def test_cutoff_skips_unlinked_classes_but_manual_submit_does_not(orch, monkeypatch):
    submitted = _cutoff_setup(orch, monkeypatch, telegram=True)
    orch.submit_all_classes(submission_date=iso(0), linked_only=True)
    assert submitted == ['3 UKM']
    submitted.clear()
    orch.submit_all_classes(submission_date=iso(0))          # Submit remaining / manual
    assert submitted == ['3 UKM', '3 UM']


def test_without_telegram_the_cutoff_still_submits_every_class(orch, monkeypatch):
    submitted = _cutoff_setup(orch, monkeypatch, telegram=False)
    orch.submit_all_classes(submission_date=iso(0), linked_only=True)
    assert submitted == ['3 UKM', '3 UM']


def test_scheduled_cutoff_asks_for_linked_only():
    from src.idme.scheduler import IDMEScheduler

    class Orch:
        def __init__(self):
            self.kwargs = None

        def classes_completed_on(self, day):
            return set()

        def submit_all_classes(self, **kwargs):
            self.kwargs = kwargs
            return []

    o = Orch()
    s = IDMEScheduler(o, [{'name': 'morning', 'label': 'M', 'cutoff': '11:30', 'forms': [3]}])
    s.running = False
    s._execute(s.sessions[0])
    assert o.kwargs['linked_only'] is True
