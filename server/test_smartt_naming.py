"""Smartt rename (2026-11): pre-rename DATANG_* settings and ~/.datang_* state
files must keep working."""

from src.config import env, state_path


def test_env_prefers_new_name(monkeypatch):
    monkeypatch.setenv("SMARTT_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DATANG_LOG_LEVEL", "ERROR")
    assert env("SMARTT_LOG_LEVEL", "DATANG_LOG_LEVEL", "INFO") == "DEBUG"


def test_env_falls_back_to_legacy_then_default(monkeypatch):
    monkeypatch.delenv("SMARTT_LOG_LEVEL", raising=False)
    monkeypatch.setenv("DATANG_LOG_LEVEL", "ERROR")
    assert env("SMARTT_LOG_LEVEL", "DATANG_LOG_LEVEL", "INFO") == "ERROR"
    monkeypatch.delenv("DATANG_LOG_LEVEL")
    assert env("SMARTT_LOG_LEVEL", "DATANG_LOG_LEVEL", "INFO") == "INFO"


def test_state_path_new_install(tmp_path):
    new, old = tmp_path / ".smartt_queue.db", tmp_path / ".datang_reader_queue.db"
    assert state_path(str(new), str(old)) == str(new)
    assert not new.exists()


def test_state_path_migrates_legacy_file(tmp_path):
    new, old = tmp_path / ".smartt_queue.db", tmp_path / ".datang_reader_queue.db"
    old.write_text("queue")
    assert state_path(str(new), str(old)) == str(new)
    assert new.read_text() == "queue" and not old.exists()


def test_state_path_new_file_wins(tmp_path):
    new, old = tmp_path / ".smartt_token", tmp_path / ".datang_reader_token"
    new.write_text("new"); old.write_text("old")
    assert state_path(str(new), str(old)) == str(new)
    assert old.read_text() == "old"  # left alone


def test_state_path_keeps_unclean_sqlite_in_place(tmp_path):
    new, old = tmp_path / ".smartt_queue.db", tmp_path / ".datang_reader_queue.db"
    old.write_text("db"); (tmp_path / ".datang_reader_queue.db-wal").write_text("wal")
    assert state_path(str(new), str(old)) == str(old)
    assert old.exists() and not new.exists()
