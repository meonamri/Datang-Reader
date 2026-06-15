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


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Add any missing identity-registry columns to existing databases."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(students)")}
    for col, col_type in _STUDENT_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE students ADD COLUMN {col} {col_type}")
    # Create the idpelajar index here (not in schema.sql): on an existing DB the
    # column doesn't exist until the ALTER above, so the index must be created
    # only once the column is guaranteed present. Idempotent.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_students_idpelajar ON students(idpelajar)"
    )
    conn.commit()
