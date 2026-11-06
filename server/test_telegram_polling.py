"""
Unit tests for the Telegram long-poll loop's timeout and backoff.

Two bugs made Smartt hammer getUpdates. `_call` took `timeout` as its own keyword,
so the long-poll wait never reached Telegram and every empty poll returned at once.
And `_call` turned every failure into an empty result, so the loop never reached
its only sleep: 15 "retry after 5" replies arrived in 2.5 seconds on 2026-11-05.

Sends must keep their old contract: a failed send returns None and is NOT retried,
because a timeout does not prove Telegram didn't deliver it.

Fake HTTP session and fake waits — no network, no real token. Run directly
(`python test_telegram_polling.py`) or under pytest.
"""

import logging
import os
import tempfile
import threading
import unittest
from unittest.mock import MagicMock

import requests

from src.idme.telegram_bot import IDMETelegramBot, _POLL_BACKOFF_MAX, _POLL_TIMEOUT

TOKEN = '123456:FAKE-TOKEN'


def reply(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


OK_EMPTY = {'ok': True, 'result': []}
BAD_GATEWAY = {'ok': False, 'error_code': 502, 'description': 'Bad Gateway'}
RATE_LIMITED = {
    'ok': False, 'error_code': 429,
    'description': 'Too Many Requests: retry after 5',
    'parameters': {'retry_after': 5},
}


class FakeSession:
    """Plays back scripted replies, then runs `on_exhausted` (stops the loop)."""

    def __init__(self, script, on_exhausted=None):
        self.script = list(script)
        self.on_exhausted = on_exhausted
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append({'url': url, 'json': json, 'timeout': timeout})
        step = self.script.pop(0) if self.script else OK_EMPTY
        if not self.script and self.on_exhausted:
            self.on_exhausted()
        if isinstance(step, Exception):
            raise step
        return step if isinstance(step, MagicMock) else reply(step)


class FakeStopEvent:
    """Records backoff waits without really waiting."""

    def __init__(self):
        self.waits = []

    def wait(self, delay):
        self.waits.append(delay)

    def set(self):
        pass

    def clear(self):
        pass


class PollingTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bot = IDMETelegramBot(
            TOKEN, MagicMock(), MagicMock(), MagicMock(),
            os.path.join(tmp.name, 'test.db'),
        )
        self.bot._stop_event = FakeStopEvent()

    def run_loop(self, script):
        """Run the real poll loop over `script`; return (session, waits)."""
        session = FakeSession(script, on_exhausted=self.finish)
        self.bot.client._session = session
        self.bot.running = True
        self.bot._poll_loop()
        return session, self.bot._stop_event.waits

    def finish(self):
        self.bot.running = False


class TestLongPollTimeout(PollingTestCase):
    def test_wait_is_sent_to_telegram_and_http_timeout_outlasts_it(self):
        session, _ = self.run_loop([OK_EMPTY])
        call = session.calls[0]
        self.assertEqual(call['json']['timeout'], _POLL_TIMEOUT)
        self.assertGreater(call['timeout'], _POLL_TIMEOUT)

    def test_empty_poll_is_not_a_failure(self):
        session, waits = self.run_loop([OK_EMPTY, OK_EMPTY, OK_EMPTY])
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(waits, [])


class TestBackoff(PollingTestCase):
    def test_429_waits_at_least_retry_after(self):
        session, waits = self.run_loop([RATE_LIMITED, RATE_LIMITED, OK_EMPTY])
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(len(waits), 2)
        self.assertTrue(all(w >= 5 for w in waits), waits)

    def test_5xx_escalates_then_resets_after_success(self):
        _, waits = self.run_loop(
            [BAD_GATEWAY, BAD_GATEWAY, BAD_GATEWAY, OK_EMPTY, BAD_GATEWAY, OK_EMPTY])
        self.assertEqual(len(waits), 4)
        self.assertTrue(1 <= waits[0] <= 2, waits)
        self.assertTrue(2 <= waits[1] <= 3, waits)
        self.assertTrue(4 <= waits[2] <= 5, waits)
        self.assertTrue(1 <= waits[3] <= 2, waits)  # reset by the success

    def test_backoff_is_capped(self):
        _, waits = self.run_loop([BAD_GATEWAY] * 12 + [OK_EMPTY])
        self.assertEqual(len(waits), 12)
        self.assertTrue(max(waits) <= _POLL_BACKOFF_MAX + 1, waits)

    def test_transport_timeout_backs_off(self):
        _, waits = self.run_loop([requests.exceptions.ReadTimeout('Read timed out'), OK_EMPTY])
        self.assertEqual(len(waits), 1)

    def test_malformed_json_backs_off(self):
        bad = MagicMock()
        bad.json.side_effect = ValueError('not json')
        _, waits = self.run_loop([bad, OK_EMPTY])
        self.assertEqual(len(waits), 1)

    def test_stop_interrupts_a_backoff(self):
        self.bot._stop_event = threading.Event()
        entered = threading.Event()

        def post(url, json=None, timeout=None):
            entered.set()
            return reply(RATE_LIMITED)

        session = MagicMock()
        session.post.side_effect = post
        self.bot.client._session = session
        self.bot.running = True
        thread = threading.Thread(target=self.bot._poll_loop, daemon=True)
        thread.start()
        self.assertTrue(entered.wait(2))
        self.bot.stop()
        thread.join(2)
        self.assertFalse(thread.is_alive())


class TestDispatch(PollingTestCase):
    def test_updates_are_dispatched_and_offset_advances(self):
        self.bot._dispatch = MagicMock()
        update = {'update_id': 100, 'message': {}}
        session, waits = self.run_loop([{'ok': True, 'result': [update]}, OK_EMPTY])
        self.bot._dispatch.assert_called_once_with(update)
        self.assertEqual(session.calls[1]['json']['offset'], 101)
        self.assertEqual(waits, [])

    def test_handler_error_does_not_trigger_backoff(self):
        self.bot._dispatch = MagicMock(side_effect=RuntimeError('handler'))
        update = {'update_id': 100, 'message': {}}
        _, waits = self.run_loop([{'ok': True, 'result': [update]}, OK_EMPTY])
        self.assertEqual(waits, [])


class TestSendsKeepTheirContract(PollingTestCase):
    def send(self, step):
        session = FakeSession([step])
        self.bot.client._session = session
        return session, self.bot.client.send_message(1, 'hello')

    def test_success_returns_the_result(self):
        _, result = self.send({'ok': True, 'result': {'message_id': 7}})
        self.assertEqual(result, {'message_id': 7})

    def test_failed_send_returns_none_and_is_not_retried(self):
        for step in (RATE_LIMITED, BAD_GATEWAY, requests.exceptions.ReadTimeout('t')):
            session, result = self.send(step)
            self.assertIsNone(result)
            self.assertEqual(len(session.calls), 1)

    def test_send_body_carries_no_long_poll_timeout(self):
        session, _ = self.send(OK_EMPTY)
        self.assertNotIn('timeout', session.calls[0]['json'])


class TestTokenStaysOutOfLogs(PollingTestCase):
    def test_connection_error_url_is_redacted(self):
        error = requests.exceptions.ConnectionError(
            f"Max retries exceeded with url: /bot{TOKEN}/sendMessage")
        self.bot.client._session = FakeSession([error])
        with self.assertLogs(level=logging.WARNING) as logs:
            self.bot.client.send_message(1, 'hello')
        self.assertNotIn(TOKEN, '\n'.join(logs.output))


if __name__ == '__main__':
    unittest.main()
