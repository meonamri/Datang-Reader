"""
Idempotent additive schema migrations for idme_data.db.

`schema.sql` (run via executescript on every init) only creates objects that do
not yet exist — `CREATE TABLE IF NOT EXISTS students (...)` is a NO-OP once the
table exists, so new COLUMNS added to that block never reach an existing DB.
This module bridges that gap: it inspects the live schema and `ALTER TABLE ... ADD
COLUMN`s anything missing. New TABLES/INDEXES are handled by schema.sql itself.

Called from both RosterManager._ensure_db and ScanTracker._ensure_db (either may
be the first to touch the DB), so it must be safe to run repeatedly.
"""

import sqlite3


# Identity-registry columns added to the `students` table (see
# IDENTITY_RESOLUTION_DESIGN.md §4). name -> column DDL type.
_STUDENT_COLUMNS = {
    "idpelajar": "TEXT",
    "tag_source": "TEXT",
    "tag_updated_at": "TIMESTAMP",
    "source": "TEXT",
}

# Login-test result columns added to the `teachers` table. The settings UI shows
# a per-teacher login chip (Verified / Re-test / Wrong password); these persist
# the last probe so the chip survives a reload and can expire after a window.
# name -> column DDL type.
_TEACHER_COLUMNS = {
    "login_test_status": "TEXT",        # 'ok' | 'fail' | NULL (untested)
    "login_test_at": "TIMESTAMP",       # ISO timestamp of the last probe
    "telegram_chat_id": "TEXT",         # Telegram chat id, set when the teacher links their chat
    "telegram_link_token": "TEXT",      # one-time deep-link token (cleared after linking)
}


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict) -> None:
    """ALTER TABLE ... ADD COLUMN for any column in `columns` not already present.
    A no-op once the column exists, so safe to run on every startup."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for col, col_type in columns.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Add any missing additive columns to existing databases."""
    _add_missing_columns(conn, "students", _STUDENT_COLUMNS)
    _add_missing_columns(conn, "teachers", _TEACHER_COLUMNS)
    # Create the idpelajar index here (not in schema.sql): on an existing DB the
    # column doesn't exist until the ALTER above, so the index must be created
    # only once the column is guaranteed present. Idempotent.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_students_idpelajar ON students(idpelajar)"
    )
    conn.commit()
