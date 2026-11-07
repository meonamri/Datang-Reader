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
}

# Teacher-response integrity metadata for durable blocked submissions.
_SUBMISSION_COLUMNS = {
    "unanswered_count": "INTEGER NOT NULL DEFAULT 0",
    "requested_confirm": "INTEGER",
    "portal_status": "TEXT",            # status text read from the portal after submit
    "form_submitted": "INTEGER",        # 1 if the submit step reported a portal status
    "write_attempted": "INTEGER",       # 1 if the submit click fired
}

# When Telegram accepted each student's prompt. NULL means it did not confirm the
# send, or the prompt predates this column.
_PROMPT_ENTRY_COLUMNS = {
    "sent_at": "TIMESTAMP",
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
    _add_missing_columns(conn, "idme_submissions", _SUBMISSION_COLUMNS)
    # Create the idpelajar index here (not in schema.sql): on an existing DB the
    # column doesn't exist until the ALTER above, so the index must be created
    # only once the column is guaranteed present. Idempotent.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_students_idpelajar ON students(idpelajar)"
    )
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS roster_sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_date DATE NOT NULL,
            class_name TEXT NOT NULL,
            teacher_id INTEGER,
            trigger TEXT NOT NULL,
            status TEXT NOT NULL,
            portal_total INTEGER,
            added_count INTEGER NOT NULL DEFAULT 0,
            renamed_count INTEGER NOT NULL DEFAULT 0,
            retired_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            started_at TIMESTAMP NOT NULL,
            completed_at TIMESTAMP NOT NULL,
            duration_seconds REAL NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_roster_sync_date_class
            ON roster_sync_runs(sync_date, class_name, id);
        CREATE TABLE IF NOT EXISTS telegram_prompt_entries (
            entry_id TEXT PRIMARY KEY,
            teacher_id INTEGER NOT NULL,
            class_name TEXT NOT NULL,
            student_name TEXT NOT NULL,
            idpelajar TEXT,
            scan_date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_tg_prompt_entries_date
            ON telegram_prompt_entries(scan_date);
    """)
    _add_missing_columns(conn, "telegram_prompt_entries", _PROMPT_ENTRY_COLUMNS)
    conn.commit()
