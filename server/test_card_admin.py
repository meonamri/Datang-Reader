"""/cards admin screen (src/card_admin.py): assign, replace, retire, audit."""
import sqlite3
from datetime import datetime

import pytest

from src.card_admin import CardAdmin, CardConflict, create_cards_blueprint
from src.local_attendance import LocalAttendanceStore


def _add_student(db, name, cls, tag=None):
    c = sqlite3.connect(db)
    cur = c.execute("INSERT INTO students (name, class_name, integration_tag, tag_source, enabled) "
                    "VALUES (?, ?, ?, ?, 1)", (name, cls, tag, "learned" if tag else None))
    c.commit()
    return cur.lastrowid


def _q(db, sql, *a):
    return sqlite3.connect(db).execute(sql, a).fetchall()


@pytest.fixture
def env(tmp_path):
    store = LocalAttendanceStore(str(tmp_path / "idme.db"), mode="local")
    ali = _add_student(store.db_path, "ALI", "5 UKM", "0000000001")
    siti = _add_student(store.db_path, "NUR'AIN", "5 UKM")
    return store, CardAdmin(store), ali, siti


def test_assign_card_to_student_without_one(env):
    store, admin, ali, siti = env
    out = admin.assign("0000000099", student_id=siti, actor="office", note="new card")
    assert out["holder"] == "NUR'AIN (5 UKM)"
    assert store.record("0000000099")["data"]["name"] == "NUR'AIN"
    assert _q(store.db_path, "select tag_source from students where id=?", siti) == [("admin",)]
    assert admin.audit()[0]["action"] == "assign" and admin.audit()[0]["actor"] == "office"


def test_replacing_a_card_retires_the_old_one(env):
    store, admin, ali, _ = env
    out = admin.assign("0000000002", student_id=ali)
    assert out["retired_previous"] == ["0000000001"]
    assert store.record("0000000002")["success"]
    old = store.record("0000000001")
    assert not old["success"] and old["status"] == "retired_card"


def test_retired_card_stays_retired_even_if_history_knew_it(env):
    store, admin, ali, _ = env
    c = sqlite3.connect(store.db_path)
    c.execute("insert into daily_scans (student_name, class_name, integration_tag, scan_time, scan_date) "
              "values ('ALI','5 UKM','0000000001','2026-10-01T07:00:00','2026-10-01')")
    c.commit()
    store.seed_from_history()
    admin.retire("0000000001", note="lost")
    store.seed_from_history()
    store.learn_from_datang("0000000001", {"name": "ALI", "section": "5 UKM"})
    assert store.record("0000000001")["status"] == "retired_card"
    assert _q(store.db_path, "select integration_tag from students where id=?", ali) == [(None,)]


def test_moving_someone_elses_card_needs_force(env):
    store, admin, ali, siti = env
    with pytest.raises(CardConflict) as e:
        admin.assign("0000000001", student_id=siti)
    assert e.value.holder["name"] == "ALI"
    admin.assign("0000000001", student_id=siti, force=True)
    assert store.record("0000000001")["data"]["name"] == "NUR'AIN"
    assert _q(store.db_path, "select integration_tag from students where id=?", ali) == [(None,)]


def test_reassigning_same_card_to_same_student_is_a_noop_not_a_conflict(env):
    store, admin, ali, _ = env
    assert admin.assign("0000000001", student_id=ali)["retired_previous"] == []


def test_student_outside_any_roster(env):
    store, admin, _, _ = env
    admin.assign("0000000050", name="bob", class_name="4 UKM")
    assert store.record("0000000050")["data"]["section"] == "4 UKM"
    admin.assign("0000000051", name="BOB", class_name="4 UKM")      # replacement card
    assert store.record("0000000050")["status"] == "retired_card"
    assert store.record("0000000051")["data"]["name"] == "BOB"


def test_found_card_can_be_reinstated(env):
    store, admin, ali, _ = env
    admin.retire("0000000001")
    admin.assign("0000000001", student_id=ali)
    assert store.record("0000000001")["success"]


def test_unknown_list_drops_cards_once_assigned(env):
    store, admin, _, siti = env
    store.record("0000000777")
    assert [c["card_id"] for c in admin.unknown()] == ["0000000777"]
    admin.assign("0000000777", student_id=siti)
    assert admin.unknown() == []
    assert _q(store.db_path, "select resolved from unmatched_scans where card_id='0000000777'") == [(1,)]


@pytest.mark.parametrize("card", ["123", "abcdefghij", "00000000011"])
def test_bad_card_numbers_rejected(env, card):
    _, admin, ali, _ = env
    with pytest.raises(ValueError):
        admin.assign(card, student_id=ali)


def test_search_by_card_name_and_class(env):
    store, admin, _, _ = env
    admin.assign("0000000050", name="BOB", class_name="4 UKM")
    assert [p["name"] for p in admin.search("0000000001")] == ["ALI"]
    assert [p["name"] for p in admin.search("nur'")] == ["NUR'AIN"]
    assert [p["name"] for p in admin.search("4 UKM")] == ["BOB"]
    assert {p["name"] for p in admin.search("5 UKM")} == {"ALI", "NUR'AIN"}


def test_admin_tag_not_overwritten_by_datang_name_match(env):
    """ScanTracker._learn_tag must not undo a card set on this screen."""
    from src.idme.scan_tracker import ScanTracker
    store, admin, ali, _ = env
    admin.assign("0000000002", student_id=ali)
    ScanTracker(str(store.db_path)).record_scan("0000000009", {"name": "ALI", "section": "5 UKM"})
    assert _q(store.db_path, "select integration_tag from students where id=?", ali) == [("0000000002",)]


# ------------------------------------------------------------------ HTTP
@pytest.fixture
def client(env):
    from flask import Flask
    store = env[0]
    app = Flask(__name__)
    app.register_blueprint(create_cards_blueprint(lambda: store))
    return app.test_client(), env


H = {"X-Requested-With": "cards-ui"}


def test_http_flow(client):
    c, (store, admin, ali, siti) = client
    assert c.get("/cards").status_code == 200
    assert "RFID cards" in c.get("/cards").get_data(as_text=True)
    s = c.get("/cards/api/summary").get_json()
    assert s["roster_students"] == 2 and s["roster_with_card"] == 1 and "5 UKM" in s["classes"]
    r = c.post("/cards/api/assign", json={"card_id": "0000000001", "student_id": siti}, headers=H)
    assert r.status_code == 409 and r.get_json()["conflict"]["name"] == "ALI"
    r = c.post("/cards/api/assign", json={"card_id": "0000000001", "student_id": siti, "force": True,
                                          "by": "Cikgu Amir"},
               headers={**H, "Tailscale-User-Login": "amir@example.com"})
    assert r.get_json()["ok"]
    assert c.get("/cards/api/audit").get_json()["changes"][0]["actor"] == "amir@example.com / Cikgu Amir"
    assert c.post("/cards/api/retire", json={"card_id": "0000000001"}, headers=H).get_json()["ok"]
    assert c.post("/cards/api/assign", json={"card_id": "12"}, headers=H).status_code == 400


def test_post_without_header_is_refused(client):
    c, (_, _, ali, _) = client
    r = c.post("/cards/api/retire", json={"card_id": "0000000001"})
    assert r.status_code == 403


def test_card_screen_works_in_datang_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENDANCE_MODE", "datang")
    monkeypatch.setenv("ATTENDANCE_DB_PATH", str(tmp_path / "idme.db"))
    from src.config import Config
    monkeypatch.setattr(Config, "DATABASE_FILE", str(tmp_path / "queue.db"))
    from src import http_server
    app, sm = http_server.create_app(use_mock_api=True)
    assert sm.local_attendance is None
    c = app.test_client()
    assert c.get("/cards/api/summary").get_json()["mode"] == "datang"
