-- IDME Module Database Schema
-- Separate database: idme_data.db (does NOT touch Datang's queue database)

-- Student identity registry (seeded from the MOEIS portal and/or school Excel;
-- learns RFID tags passively from the scan stream). See
-- src/idme/IDENTITY_RESOLUTION_DESIGN.md.
-- NOTE: the identity columns below (idpelajar/tag_source/tag_updated_at/source)
-- are also added to EXISTING databases by migrations.apply_migrations(), because
-- CREATE TABLE IF NOT EXISTS is a no-op once the table exists.
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT,                    -- School ID from Excel
    name TEXT NOT NULL,                 -- Full name (uppercase)
    ic_number TEXT,                     -- Malaysian IC (12 digits), nullable
    class_name TEXT NOT NULL,           -- e.g., '5 UKM'
    integration_tag TEXT,              -- CURRENT (possibly learned) RFID card ID
    idpelajar TEXT,                    -- MOEIS data-idpelajar (portal student id)
    tag_source TEXT,                   -- 'excel' | 'learned' | NULL
    tag_updated_at TIMESTAMP,          -- when integration_tag was last set/changed
    source TEXT,                       -- 'portal' | 'excel'
    enabled BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_students_class ON students(class_name);
CREATE INDEX IF NOT EXISTS idx_students_tag ON students(integration_tag);
CREATE INDEX IF NOT EXISTS idx_students_name ON students(name);
-- idx_students_idpelajar is created by migrations.apply_migrations() AFTER the
-- column is guaranteed present (an existing DB won't have it when this script
-- runs, so referencing it here would error inside executescript).

-- Scans we could not tie to any registry student (the alert surface for the
-- settings-UI coverage panel). Deduped per (card_id, scan_date).
CREATE TABLE IF NOT EXISTS unmatched_scans (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id      TEXT NOT NULL,
    scan_name    TEXT NOT NULL,      -- name Datang returned
    scan_class   TEXT,              -- section Datang returned
    scan_date    DATE NOT NULL,
    reason       TEXT,              -- 'no_match' | 'ambiguous'
    resolved     BOOLEAN DEFAULT 0,  -- set when an admin maps/ignores it
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_unmatched_unique
    ON unmatched_scans(card_id, scan_date);
CREATE INDEX IF NOT EXISTS idx_unmatched_date ON unmatched_scans(scan_date);

-- Teacher credentials (managed via Web UI at /idme/settings)
CREATE TABLE IF NOT EXISTS teachers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    ic_number TEXT NOT NULL UNIQUE,         -- IDME login credential (12 digits)
    encrypted_password TEXT NOT NULL,       -- Fernet encrypted password
    class_name TEXT NOT NULL,              -- Class assigned to this teacher
    enabled BOOLEAN DEFAULT 1,
    login_test_status TEXT,                 -- last login probe: 'ok' | 'fail' | NULL (untested)
    login_test_at TIMESTAMP,                -- when the last login probe ran (ISO)
    telegram_chat_id TEXT,                  -- Telegram chat id (set when the teacher links their chat)
    telegram_link_token TEXT,               -- one-time deep-link token (cleared after linking)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- NOTE: login_test_* and telegram_* are also added to EXISTING databases by
-- migrations.apply_migrations() (CREATE TABLE IF NOT EXISTS is a no-op once the
-- table exists, so new columns never reach an already-created teachers table).
CREATE INDEX IF NOT EXISTS idx_teachers_class ON teachers(class_name);

-- Daily scan records (populated as students tap RFID cards)
CREATE TABLE IF NOT EXISTS daily_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_name TEXT NOT NULL,             -- Name from Datang API response
    class_name TEXT NOT NULL,               -- Section from Datang API response
    integration_tag TEXT,                   -- RFID card ID
    scan_time TEXT NOT NULL,                -- ISO format time
    scan_date DATE NOT NULL,                -- YYYY-MM-DD
    datang_pid TEXT,                        -- person_id from Datang API
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_scans_date ON daily_scans(scan_date);
CREATE INDEX IF NOT EXISTS idx_scans_class_date ON daily_scans(class_name, scan_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_scans_unique
    ON daily_scans(student_name, class_name, scan_date);

-- Per-student absence reasons collected before the cutoff (e.g. via the Telegram
-- bot). detect_absences merges these over the default reason (MALAS KE SEKOLAH);
-- a student with no row here keeps the default. Upserted on the unique index so a
-- teacher can change a reason any time before the cutoff submits.
CREATE TABLE IF NOT EXISTS absence_reasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date    DATE NOT NULL,
    class_name   TEXT NOT NULL,
    student_name TEXT NOT NULL,        -- uppercase roster name (name merge key)
    idpelajar    TEXT,                 -- MOEIS portal student id (preferred match when known)
    sebab_id     TEXT NOT NULL,        -- MOEIS sebab code, e.g. 'D0010075'
    category     TEXT NOT NULL,        -- MOEIS category, derived from sebab_id
    set_by       INTEGER,              -- teachers.id that recorded the reason
    source       TEXT DEFAULT 'telegram',
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_absence_reasons_unique
    ON absence_reasons(scan_date, class_name, student_name);
CREATE INDEX IF NOT EXISTS idx_absence_reasons_date ON absence_reasons(scan_date);

-- IDME submission log (tracks what was submitted when)
CREATE TABLE IF NOT EXISTS idme_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    class_name TEXT NOT NULL,
    submission_date DATE NOT NULL,
    total_roster INTEGER NOT NULL DEFAULT 0,
    total_scanned INTEGER NOT NULL DEFAULT 0,
    total_absent INTEGER NOT NULL DEFAULT 0,
    successful INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',          -- pending, running, completed, failed
    error_message TEXT,
    duration_seconds REAL,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_submissions_date ON idme_submissions(submission_date);
CREATE INDEX IF NOT EXISTS idx_submissions_class ON idme_submissions(class_name);

-- IDME session cache (cookies + CSRF token per teacher)
CREATE TABLE IF NOT EXISTS session_cache (
    teacher_id INTEGER PRIMARY KEY,
    cookies TEXT NOT NULL,                  -- JSON serialized cookie array
    csrf_token TEXT,
    created_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    last_used TIMESTAMP
);
