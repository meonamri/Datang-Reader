"""Reader outbox (client/gui/outbox.py) + server idempotency (src/request_log.py).

The end-to-end tests route the outbox's requests.post into the real Flask app
(Flask test client), so they exercise outbox -> POST /card -> request_log ->
ServiceManager exactly as a reader would."""
import os
import sqlite3
import sys
from datetime import datetime, timedelta

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "client", "gui"))
import outbox as ob  # noqa: E402

from src.request_log import RequestLog  # noqa: E402


class Resp:
    def __init__(self, code, body):
        self.status_code, self._body = code, body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


@pytest.fixture
def box(tmp_path):
    return ob.Outbox(str(tmp_path / "outbox.db"), reader_id="smksat-test")


def _status(box):
    return [r[0] for r in sqlite3.connect(box.path).execute("select status from taps order by scanned_at")]


def test_tap_is_saved_before_any_network(box):
    row = box.add("0001234567")
    assert datetime.fromisoformat(row["scanned_at"]).tzinfo is not None   # carries its UTC offset
    assert _status(box) == ["pending"]
    assert box.get(row["event_id"])["card_id"] == "0001234567"   # leading zeros kept


@pytest.mark.parametrize("exc,idempotent,expected", [
    (requests.exceptions.ConnectionError("refused"), False, "pending"),   # never sent: always resend
    (requests.exceptions.ConnectTimeout("t"), False, "pending"),
    (requests.exceptions.ReadTimeout("t"), True, "pending"),             # ambiguous, server dedups
    (requests.exceptions.ReadTimeout("t"), False, "uncertain"),          # ambiguous, old server: hold
])
def test_failure_classification(box, monkeypatch, exc, idempotent, expected):
    def post(*a, **k):
        raise exc
    monkeypatch.setattr(ob.requests, "post", post)
    row = box.add("0000000001")
    verdict, _, _ = ob.deliver(box, box.get(row["event_id"]), "http://x/card", 1, idempotent)
    assert _status(box) == [expected]
    assert box.get(row["event_id"])["attempts"] == 1


@pytest.mark.parametrize("code,body,expected", [
    (200, {"success": True, "data": {}}, "delivered"),
    (200, {"success": False, "message": "CARD_NOT_FOUND"}, "delivered"),   # final refusal
    (400, None, "delivered"),
    (409, {"status": "processing"}, "pending"),
    (502, None, "uncertain"),
])
def test_http_classification_against_old_server(box, monkeypatch, code, body, expected):
    monkeypatch.setattr(ob.requests, "post", lambda *a, **k: Resp(code, body))
    row = box.add("0000000001")
    ob.deliver(box, box.get(row["event_id"]), "http://x/card", 1, server_idempotent=False)
    assert _status(box) == [expected]


def test_hold_keeps_sync_loop_off_a_tap_in_flight(box):
    box.add("0000000001", hold_seconds=60)
    assert box.due() == []
    box.add("0000000002")
    assert [r["card_id"] for r in box.due()] == ["0000000002"]


def test_backoff_grows_and_sync_stops_at_first_failure(box, monkeypatch):
    calls = []

    def post(url, json, timeout):
        calls.append(json["card_id"])
        raise requests.exceptions.ConnectionError("down")
    monkeypatch.setattr(ob.requests, "post", post)
    box.add("0000000001")
    box.add("0000000002")
    assert ob.sync_due(box, "http://x/card", 1, True) == []
    assert calls == ["0000000001"]                 # stopped after the first failure
    nxt = box.get(box.due()[0]["event_id"])         # the second is still due
    assert nxt["card_id"] == "0000000002"


def test_purge_keeps_pending(box):
    a = box.add("0000000001")
    b = box.add("0000000002")
    box.mark_delivered(a["event_id"], {"success": True})
    c = sqlite3.connect(box.path)
    c.execute("update taps set delivered_at = ?", ((datetime.now() - timedelta(days=40)).isoformat(),))
    c.commit()
    assert box.purge() == 1
    assert _status(box) == ["pending"]


# ------------------------------------------------------------ request_log
def test_request_log_states(tmp_path):
    log = RequestLog(str(tmp_path / "q.db"))
    assert log.begin("e1", "0000000001") == ("new", None)
    assert log.begin("e1", "0000000001") == ("busy", None)
    log.finish("e1", {"success": True, "message": "ok"})
    state, body = log.begin("e1", "0000000001")
    assert state == "done" and body["success"] and body["replayed"]


def test_request_log_stale_processing_is_never_reprocessed(tmp_path):
    log = RequestLog(str(tmp_path / "q.db"))
    log.begin("e1", "0000000001")
    c = sqlite3.connect(log.db_file)
    c.execute("update card_requests set created_at = ?", ((datetime.now() - timedelta(hours=1)).isoformat(),))
    c.commit()
    state, body = log.begin("e1", "0000000001")
    assert state == "done" and body["status"] == "uncertain" and not body["success"]


# ------------------------------------------------------------- end to end
@pytest.fixture
def app_client(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDANCE_MODE", "datang")
    from src.config import Config
    monkeypatch.setattr(Config, "DATABASE_FILE", str(tmp_path / "queue.db"))
    from src import http_server
    app, sm = http_server.create_app(use_mock_api=True)
    sm.api_client.token = "tok"
    seen = []
    real = sm.api_client.submit_attendance

    def counting(**k):
        seen.append(k["card_id"])
        return real(**k)
    sm.api_client.submit_attendance = counting
    return app.test_client(), sm, seen


def _route_outbox_to(monkeypatch, client, fail_first=0):
    state = {"n": 0}

    def post(url, json, timeout):
        r = client.post("/card", json=json)
        state["n"] += 1
        if state["n"] <= fail_first:
            # the server DID process it, but the reader never saw the answer
            raise requests.exceptions.ReadTimeout("reader gave up after 5 s")
        return Resp(r.status_code, r.get_json())
    monkeypatch.setattr(ob.requests, "post", post)


def test_resend_after_timeout_reaches_datang_once(box, monkeypatch, app_client):
    client, sm, seen = app_client
    _route_outbox_to(monkeypatch, client, fail_first=1)
    row = box.add("0000000123")
    v1, _, _ = ob.deliver(box, box.get(row["event_id"]), "http://s/card", 5, server_idempotent=True)
    assert v1 == ob.AMBIGUOUS and _status(box) == ["pending"]
    sqlite3.connect(box.path).execute("update taps set next_attempt = '2000-01-01'").connection.commit()
    done = ob.sync_due(box, "http://s/card", 5, server_idempotent=True)
    assert len(done) == 1 and done[0][1]["success"] and done[0][1]["replayed"]
    assert seen == ["0000000123"]            # Datang.my saw the tap exactly once
    assert _status(box) == ["delivered"]


def test_status_advertises_capability(app_client):
    client, _, _ = app_client
    assert "card_event_id" in client.get("/status").get_json()["capabilities"]


def test_offline_tap_keeps_its_real_date(box, monkeypatch, app_client, tmp_path):
    """A tap saved yesterday and delivered today is filed under yesterday in
    the IDME daily_scans table, even though Datang.my stamps it today."""
    client, sm, _ = app_client
    from src.idme.scan_tracker import ScanTracker
    sm.scan_tracker = ScanTracker(str(tmp_path / "idme.db"))
    _route_outbox_to(monkeypatch, client)
    yesterday = datetime.now().astimezone() - timedelta(days=1)
    box.add("0000000777", when=yesterday)
    assert ob.sync_due(box, "http://s/card", 5, True)[0][1]["success"]
    dates = sqlite3.connect(str(tmp_path / "idme.db")).execute("select scan_date from daily_scans").fetchall()
    assert dates == [(yesterday.date().isoformat(),)]


def test_old_style_request_without_event_id_still_works(app_client):
    client, _, seen = app_client
    r = client.post("/card", json={"card_id": "0000000555"})
    assert r.status_code == 200 and r.get_json()["success"] and seen == ["0000000555"]
