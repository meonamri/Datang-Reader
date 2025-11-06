# Information Disclosure Security Issues

## [HIGH] Credentials Logged During Login Attempts

**Location**: `src/api_client.py:78`

**Risk**: Username is logged during login, which combined with error messages could aid credential stuffing attacks.

**Current Code**:
```python
logger.info(f"Attempting login for user: {username}")
```

**Potential Impact**:
- Username disclosure in log files
- Aids reconnaissance for targeted attacks
- Combined with timing attacks, reveals valid usernames
- Log aggregation services expose usernames
- Compliance violations (PII logging)

**Recommended Fix Approach**:
- Never log usernames in production:
  ```python
  logger.info("Attempting login")
  # Only log username in DEBUG mode
  logger.debug(f"Login user: {username}")
  ```
- Hash usernames before logging if necessary:
  ```python
  import hashlib
  user_hash = hashlib.sha256(username.encode()).hexdigest()[:8]
  logger.info(f"Login attempt: user_{user_hash}")
  ```
- Implement structured logging with PII redaction
- Add security event logging separate from application logs
- Document no-log policy for credentials

---

## [HIGH] Full API Response Bodies Logged at DEBUG Level

**Location**: `src/api_client.py:98-100`, `191-192`

**Risk**: Complete API responses logged at DEBUG level, potentially exposing tokens, personal data, and system information.

**Current Code**:
```python
# Log response for debugging
logger.debug(f"Response status: {response.status_code}")
logger.debug(f"Response body: {response.text[:200]}")
```

**Potential Impact**:
- Tokens visible in logs if included in responses
- Personal information (names, IDs) exposed in logs
- API structure and field names leaked
- Business logic details revealed
- Sensitive error messages stored in logs
- Compliance violations (GDPR, PDPA)

**Recommended Fix Approach**:
- Implement response sanitization:
  ```python
  def sanitize_response(response_data: dict) -> dict:
      """Remove sensitive fields from response before logging"""
      SENSITIVE_KEYS = {'token', 'password', 'api_key', 'secret', 'credential'}
      sanitized = {}
      for key, value in response_data.items():
          if any(sensitive in key.lower() for sensitive in SENSITIVE_KEYS):
              sanitized[key] = '[REDACTED]'
          elif isinstance(value, dict):
              sanitized[key] = sanitize_response(value)
          else:
              sanitized[key] = value
      return sanitized

  logger.debug(f"Response: {sanitize_response(response.json())}")
  ```
- Never log full response bodies in production
- Log only response status and metadata
- Implement PII detection and redaction
- Use structured logging with automatic sanitization
- Document sensitive data handling in logs

---

## [MEDIUM] Card IDs Partially Exposed in Logs

**Location**: Multiple locations (e.g., `service_manager.py:120`, `offline_queue.py:124`)

**Risk**: Card IDs truncated to 8 characters still provide significant information for correlation attacks.

**Current Code**:
```python
logger.info(f"Processing attendance for card: {card_id[:8]}...")
logger.info(f"Queued attendance record (ID: {entry_id}, card: {card_id[:8]}...)")
```

**Potential Impact**:
- Partial card IDs allow correlation of attendance records
- Rainbow table attacks possible on truncated IDs
- Privacy violations by tracking individuals
- Compliance risks under data protection regulations
- Insider threats can correlate logs with individuals

**Recommended Fix Approach**:
- Hash card IDs before logging:
  ```python
  import hashlib

  def hash_card_id(card_id: str) -> str:
      """Return truncated hash of card ID for logging"""
      return hashlib.sha256(card_id.encode()).hexdigest()[:8]

  logger.info(f"Processing attendance for card: {hash_card_id(card_id)}")
  ```
- Use session IDs instead of card ID fragments
- Implement log anonymization for production
- Store card ID mapping separately for audit trail
- Document data minimization in logging policy

---

## [MEDIUM] Stack Traces Exposed in Error Messages

**Location**: Multiple exception handlers

**Risk**: Exception messages include full stack traces which may expose internal paths, structure, and logic.

**Current Code**:
```python
except Exception as e:
    logger.error(f"Unexpected error during login: {e}")
    # Full exception includes stack trace in logs
```

**Potential Impact**:
- File system structure revealed
- Internal implementation details leaked
- Library versions exposed (aiding exploit selection)
- Database schema hints from SQL errors
- Application logic revealed through call stack

**Recommended Fix Approach**:
- Implement error sanitization:
  ```python
  def sanitize_exception(e: Exception) -> str:
      """Return safe error message without stack trace"""
      return f"{type(e).__name__}: {str(e).split(chr(10))[0]}"

  logger.error(f"Login error: {sanitize_exception(e)}")
  # Log full traceback only in DEBUG mode
  logger.debug("Full traceback:", exc_info=True)
  ```
- Use structured exception logging
- Return generic errors to users
- Log full details server-side only
- Implement error code system for support correlation

---

## [MEDIUM] Configuration Values Logged

**Location**: `datang_reader.py:133-136`

**Risk**: Configuration values logged during status display, potentially exposing sensitive information.

**Current Code**:
```python
print(f"\nAPI URL: {Config.API_BASE_URL}")
print(f"Device ID: {Config.DEVICE_ID}")
print(f"Serial Port: {Config.SERIAL_PORT or 'auto-detect'}")
```

**Potential Impact**:
- API endpoints exposed to unauthorized users
- Internal network topology revealed
- Device identification aids targeted attacks
- Configuration details aid reconnaissance

**Recommended Fix Approach**:
- Sanitize configuration output:
  ```python
  def sanitize_url(url: str) -> str:
      """Redact credentials from URL"""
      from urllib.parse import urlparse
      parsed = urlparse(url)
      return f"{parsed.scheme}://{parsed.netloc}/[path]"

  print(f"API URL: {sanitize_url(Config.API_BASE_URL)}")
  ```
- Require authentication for configuration viewing
- Implement role-based access for sensitive config
- Log configuration access for audit trail
- Separate sensitive config into protected file

---

## [MEDIUM] Error Messages Reveal Database Internals

**Location**: `src/offline_queue.py:70-72`, `127-129`, etc.

**Risk**: SQLite error messages exposed in logs reveal database schema and structure.

**Current Code**:
```python
except sqlite3.Error as e:
    logger.error(f"Failed to initialize database: {e}")
    raise
```

**Potential Impact**:
- Database schema revealed through constraint errors
- Table and column names exposed
- SQL syntax errors aid SQL injection attempts
- Database version information leaked
- Internal implementation details revealed

**Recommended Fix Approach**:
- Sanitize database errors:
  ```python
  def sanitize_db_error(e: sqlite3.Error) -> str:
      """Return generic database error message"""
      error_map = {
          "UNIQUE constraint failed": "Duplicate entry",
          "FOREIGN KEY constraint failed": "Invalid reference",
          "no such table": "Database error",
      }
      error_str = str(e)
      for pattern, generic in error_map.items():
          if pattern in error_str:
              return generic
      return "Database operation failed"

  logger.error(f"Database error: {sanitize_db_error(e)}")
  logger.debug(f"Raw error: {e}")  # Only in DEBUG mode
  ```
- Return generic errors to users
- Log detailed errors server-side only
- Implement error code system
- Monitor for repeated errors indicating attacks

---

## [MEDIUM] Detailed Error Responses from API Logged

**Location**: `src/api_client.py:118-126`, `214-218`

**Risk**: Full API error responses logged, potentially exposing server-side implementation details.

**Current Code**:
```python
logger.error(f"No token in response: {data}")
# ...
error_msg = response_json.get("error", "Unknown error")
message = response_json.get("message", "")
logger.error(f"Attendance error: {error_msg} - {message}")
```

**Potential Impact**:
- Server-side validation rules exposed
- API implementation details revealed
- Error codes aid in attack planning
- Backend technology stack identified
- Database error messages leaked through API

**Recommended Fix Approach**:
- Sanitize API error responses:
  ```python
  def sanitize_api_error(response_data: dict) -> str:
      """Extract safe error message from API response"""
      # Map API errors to user-friendly messages
      error_code = response_data.get("code", "UNKNOWN")
      return f"API error: {error_code}"

  logger.error(f"API error: {sanitize_api_error(response_json)}")
  logger.debug(f"Full API response: {response_json}")
  ```
- Implement error code mapping
- Never expose raw API errors to users
- Log full details only in DEBUG mode
- Create allowlist of safe error messages

---

## [LOW] Version Information in User-Agent

**Location**: `src/api_client.py:52`

**Risk**: User-Agent reveals exact version, aiding version-specific exploits.

**Current Code**:
```python
'User-Agent': 'Datang-Linux-Reader/1.0'
```

**Potential Impact**:
- Version-specific vulnerabilities can be targeted
- Aids reconnaissance for exploit development
- Reveals deployment architecture
- Enables fingerprinting for automated attacks

**Recommended Fix Approach**:
- Use generic User-Agent without version:
  ```python
  'User-Agent': 'Datang-Reader'
  ```
- Implement version negotiation via API handshake
- Consider randomizing User-Agent strings
- Document version disclosure policy

---

## [LOW] Queue Statistics Exposed Without Authentication

**Location**: `datang_reader.py:148-155`

**Risk**: Queue statistics shown in status command without authentication, revealing operational details.

**Current Code**:
```python
def run_status_command():
    # No authentication check
    stats = queue.get_statistics()
    print(f"  Pending: {stats.get('pending', 0)}")
```

**Potential Impact**:
- Operational patterns revealed to unauthorized users
- Offline status disclosed (aids timing attacks)
- Queue size reveals attendance patterns
- System health information aids reconnaissance

**Recommended Fix Approach**:
- Require authentication for status command:
  ```python
  def run_status_command(require_auth=True):
      if require_auth and not verify_user_permission():
          print("Error: Authentication required")
          return 1
  ```
- Implement role-based access control
- Add --auth flag for status command
- Log status command access for audit
- Provide public vs. detailed status views

---

## [LOW] Filesystem Paths Exposed in Logs

**Location**: `src/auth_manager.py:31`, `src/offline_queue.py:33`

**Risk**: Full filesystem paths logged, revealing system structure.

**Current Code**:
```python
logger.info(f"Initialized auth manager (token file: {self.token_file})")
logger.info(f"Initialized attendance queue (database: {self.db_file})")
```

**Potential Impact**:
- Filesystem structure revealed
- Home directory paths exposed
- Operating system details inferred
- Aids in path traversal attacks
- Reveals multi-user system configuration

**Recommended Fix Approach**:
- Log only filename, not full path:
  ```python
  import os
  filename = os.path.basename(self.token_file)
  logger.info(f"Initialized auth manager (token file: {filename})")
  ```
- Use path aliases for logging:
  ```python
  def sanitize_path(path: str) -> str:
      """Replace home directory with ~"""
      return path.replace(os.path.expanduser('~'), '~')

  logger.info(f"Token file: {sanitize_path(self.token_file)}")
  ```
- Document path disclosure in security policy
- Implement path anonymization in logging configuration
