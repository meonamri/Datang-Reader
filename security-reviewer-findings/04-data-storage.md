# Data Storage Security Issues

## [HIGH] SQLite Database Not Encrypted

**Location**: `src/offline_queue.py:31`

**Risk**: Attendance queue database is stored unencrypted on disk, exposing sensitive attendance records.

**Current Code**:
```python
self.db_file = db_file or Config.DATABASE_FILE
# DATABASE_FILE = os.path.expanduser("~/.datang_reader_queue.db")
```

**Potential Impact**:
- Attendance records readable by anyone with filesystem access
- Personal information (card IDs, timestamps, device IDs) exposed
- Privacy violations under GDPR/PDPA if containing personal data
- Data accessible in backups, forensics, or stolen devices
- Insider threats can access historical attendance data

**Recommended Fix Approach**:
- Use SQLCipher for encrypted SQLite database:
  ```python
  import sqlcipher3 as sqlite3
  conn = sqlite3.connect(db_file)
  conn.execute(f"PRAGMA key = '{encryption_key}'")
  ```
- Generate encryption key from:
  - Machine-specific hardware identifier
  - System keyring/credential manager
  - User password (with PBKDF2 key derivation)
- Store key separately from database file
- Set restrictive file permissions (0600 on Unix)
- Consider full-disk encryption as baseline requirement
- Document encryption setup in deployment guide

---

## [HIGH] SQLite Database File Permissions Not Set

**Location**: `src/offline_queue.py:35-72`

**Risk**: Database file created with default permissions, potentially readable by all users.

**Current Code**:
```python
def _init_database(self):
    try:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # No file permission setting after creation
```

**Potential Impact**:
- Database readable by all local users on multi-user systems
- Attendance data exposed to other processes
- Privilege escalation via database modification
- Compliance violations for access control
- Insider threats can extract attendance records

**Recommended Fix Approach**:
- Set restrictive permissions immediately after database creation:
  ```python
  if not os.path.exists(self.db_file):
      # Create database
      conn = sqlite3.connect(self.db_file)
      # Set permissions (Unix)
      try:
          os.chmod(self.db_file, 0o600)
      except (OSError, TypeError):
          # Windows: Use ACLs
          import win32security
          # Set file readable only by current user
  ```
- Validate permissions on each connection
- Log warning if permissions are too permissive
- Add health check for database security
- Document permission requirements in deployment guide

---

## [MEDIUM] Token File Created Without Atomic Write

**Location**: `src/auth_manager.py:104-106`

**Risk**: Token file written non-atomically, creating race condition where partial token could be read.

**Current Code**:
```python
# Write token file
with open(self.token_file, 'w') as f:
    json.dump(data, f, indent=2)
```

**Potential Impact**:
- Race condition if token read during write
- Corrupted token file if process crashes during write
- Application failure on next startup
- Token loss requiring re-authentication
- Potential security bypass if partial token accepted

**Recommended Fix Approach**:
- Use atomic write with temporary file and rename:
  ```python
  import tempfile
  import shutil

  # Write to temp file
  fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(self.token_file))
  try:
      with os.fdopen(fd, 'w') as f:
          json.dump(data, f, indent=2)
      os.chmod(temp_path, 0o600)
      # Atomic rename
      shutil.move(temp_path, self.token_file)
  except:
      os.unlink(temp_path)
      raise
  ```
- Implement file locking during read/write
- Add integrity check (checksum) to token file
- Implement backup token file for recovery
- Test crash scenarios in test suite

---

## [MEDIUM] No Database Connection Pooling or Limits

**Location**: `src/offline_queue.py:74-82`

**Risk**: Each operation opens new connection without limits, risking resource exhaustion.

**Current Code**:
```python
@contextmanager
def _get_connection(self):
    """Get database connection with context manager"""
    conn = sqlite3.connect(self.db_file)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
```

**Potential Impact**:
- SQLite database locks under concurrent access
- Resource exhaustion from too many open connections
- Database corruption from concurrent writes
- Performance degradation from connection overhead
- Application hangs on database lock timeouts

**Recommended Fix Approach**:
- Implement connection pooling:
  ```python
  from queue import Queue

  class AttendanceQueue:
      def __init__(self):
          self.connection_pool = Queue(maxsize=5)
          # Pre-create connections
  ```
- Use single persistent connection with locking:
  ```python
  import threading

  self._conn_lock = threading.Lock()
  self._conn = sqlite3.connect(self.db_file, check_same_thread=False)
  ```
- Set SQLite timeout and busy handler:
  ```python
  conn.execute("PRAGMA busy_timeout = 5000")
  ```
- Add WAL mode for better concurrency:
  ```python
  conn.execute("PRAGMA journal_mode=WAL")
  ```
- Monitor connection usage and add alerting

---

## [MEDIUM] No Database Integrity Checking

**Location**: `src/offline_queue.py:35-72`

**Risk**: Database corruption not detected, leading to data loss or application failures.

**Current Code**:
```python
def _init_database(self):
    # Schema creation but no integrity check
    cursor.execute('''CREATE TABLE IF NOT EXISTS attendance_queue ...''')
```

**Potential Impact**:
- Silent data corruption goes undetected
- Application crashes from corrupted database
- Loss of queued attendance records
- Business logic errors from invalid data
- Extended downtime during corruption recovery

**Recommended Fix Approach**:
- Run integrity check on startup:
  ```python
  def check_database_integrity(self):
      with self._get_connection() as conn:
          cursor = conn.cursor()
          result = cursor.execute("PRAGMA integrity_check").fetchone()
          if result[0] != "ok":
              logger.critical(f"Database integrity check failed: {result}")
              raise DatabaseCorruptionError()
  ```
- Implement automatic backup before modifications
- Add foreign key constraints for referential integrity
- Log checksums of critical tables
- Implement database repair procedures
- Schedule periodic integrity checks
- Document backup and recovery procedures

---

## [MEDIUM] Sensitive Data Not Sanitized Before Storage

**Location**: `src/offline_queue.py:109-119`

**Risk**: Card IDs and device IDs stored without sanitization, potentially storing malicious content.

**Current Code**:
```python
cursor.execute('''
    INSERT INTO attendance_queue
    (card_id, timestamp, temperature, device_id, queued_at)
    VALUES (?, ?, ?, ?, ?)
''', (
    card_id,  # No sanitization
    timestamp.isoformat(),
    temperature,
    device_id,
    datetime.now().isoformat()
))
```

**Potential Impact**:
- XSS if data displayed in web interface (future)
- Database pollution with malicious content
- Query performance degradation from oversized strings
- Storage exhaustion from unbounded strings
- Downstream system compromise if data exported

**Recommended Fix Approach**:
- Sanitize and validate before storage:
  ```python
  def sanitize_card_id(card_id: str) -> str:
      # Limit length
      if len(card_id) > 64:
          raise ValueError("Card ID too long")
      # Remove control characters
      return ''.join(c for c in card_id if c.isprintable())
  ```
- Define maximum field lengths in schema:
  ```sql
  card_id TEXT NOT NULL CHECK(length(card_id) <= 64)
  ```
- Add CHECK constraints for data validation
- Implement data sanitization layer
- Log rejected values for security monitoring

---

## [LOW] No Database Backup Mechanism

**Location**: `src/offline_queue.py` (entire module)

**Risk**: No automated backup mechanism for attendance queue database.

**Current Code**:
```python
# No backup implementation
```

**Potential Impact**:
- Permanent data loss from corruption or hardware failure
- Inability to recover from accidental deletion
- Business continuity risk from data loss
- Compliance violations for data retention
- Lost attendance records requiring manual reconciliation

**Recommended Fix Approach**:
- Implement automatic database backup:
  ```python
  import shutil
  from datetime import datetime

  def backup_database(self):
      backup_path = f"{self.db_file}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
      shutil.copy2(self.db_file, backup_path)
      # Rotate old backups (keep last 7 days)
      self.cleanup_old_backups(days=7)
  ```
- Schedule backups before risky operations (cleanup, sync)
- Add backup verification (integrity check on backup)
- Implement restore procedure
- Store backups in separate location
- Document backup and restore procedures
- Add backup monitoring and alerting

---

## [LOW] Log Files Not Rotated Securely

**Location**: `datang_reader.py:42-49`

**Risk**: Log rotation happens but old logs not securely deleted, may contain sensitive data.

**Current Code**:
```python
file_handler = RotatingFileHandler(
    log_file,
    maxBytes=Config.LOG_MAX_BYTES,
    backupCount=Config.LOG_BACKUP_COUNT
)
```

**Potential Impact**:
- Sensitive data in old log files accessible indefinitely
- Compliance violations for data retention policies
- Storage exhaustion from accumulated logs
- Tokens or credentials leaked in debug logs still accessible

**Recommended Fix Approach**:
- Implement secure log rotation with cleanup:
  ```python
  class SecureRotatingFileHandler(RotatingFileHandler):
      def doRollover(self):
          super().doRollover()
          # Securely delete oldest backup
          if os.path.exists(self.baseFilename + f".{self.backupCount}"):
              self.secure_delete(self.baseFilename + f".{self.backupCount}")

      def secure_delete(self, filepath):
          # Overwrite before delete
          size = os.path.getsize(filepath)
          with open(filepath, 'wb') as f:
              f.write(os.urandom(size))
          os.unlink(filepath)
  ```
- Set restrictive permissions on log files (0600)
- Implement log encryption for compliance
- Add log retention policy configuration
- Document log handling for compliance audits
