-- IDME Module Database Schema
-- Separate database: idme_data.db (does NOT touch Datang's queue database)

-- Student roster (imported from school Excel export)
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT,                    -- School ID from Excel
    name TEXT NOT NULL,                 -- Full name (uppercase)
    ic_number TEXT,                     -- Malaysian IC (12 digits), nullable
    class_name TEXT NOT NULL,           -- e.g., '5 UKM'
    integration_tag TEXT,              -- RFID card ID (nullable)
    enabled BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_students_class ON students(class_name);
CREATE INDEX IF NOT EXISTS idx_students_tag ON students(integration_tag);
CREATE INDEX IF NOT EXISTS idx_students_name ON students(name);

-- Teacher credentials (managed via Web UI at /idme/settings)
CREATE TABLE IF NOT EXISTS teachers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    ic_number TEXT NOT NULL UNIQUE,         -- IDME login credential (12 digits)
    encrypted_password TEXT NOT NULL,       -- Fernet encrypted password
    class_name TEXT NOT NULL,              -- Class assigned to this teacher
    enabled BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
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
