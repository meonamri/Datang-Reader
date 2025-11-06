# Input Validation and Injection Security Issues

## [HIGH] SQL Injection via String Formatting in LIMIT Clause

**Location**: `src/offline_queue.py:152-153`

**Risk**: SQL injection vulnerability through string formatting in LIMIT clause.

**Current Code**:
```python
if limit:
    query += f' LIMIT {limit}'

cursor.execute(query, (Config.MAX_RETRY_ATTEMPTS,))
```

**Potential Impact**:
- SQL injection if `limit` parameter is controlled by attacker
- Database manipulation or data exfiltration
- Potential for arbitrary SQL execution
- Queue database corruption or deletion
- While currently only called with hardcoded values, this is a dangerous pattern

**Recommended Fix Approach**:
- Use parameterized query for LIMIT clause:
  ```python
  query += ' LIMIT ?'
  cursor.execute(query, (Config.MAX_RETRY_ATTEMPTS, limit))
  ```
- Validate limit parameter is integer before use:
  ```python
  if limit:
      limit = int(limit)  # Raises ValueError if not valid
      query += ' LIMIT ?'
  ```
- Add input validation wrapper for all SQL parameters
- Review all other SQL queries for similar issues
- Add SQL injection testing to test suite

---

## [MEDIUM] No Input Validation on Card ID

**Location**: `src/service_manager.py:108`, `src/gui_app.py:367`

**Risk**: RFID card IDs are not validated before processing, allowing arbitrary strings that could cause issues.

**Current Code**:
```python
def process_attendance(self, card_id: str, temperature: Optional[float] = None):
    timestamp = datetime.now()
    logger.info(f"Processing attendance for card: {card_id[:8]}...")
    # No validation of card_id format or content
```

**Potential Impact**:
- XSS if card ID displayed in web interface (future feature)
- SQL injection if card ID used in raw SQL (currently safe with parameterized queries)
- Log injection via newlines in card ID
- Application crashes from excessively long card IDs
- Business logic bypass with malformed card IDs

**Recommended Fix Approach**:
- Define expected card ID format (length, character set)
- Implement validation function:
  ```python
  def validate_card_id(card_id: str) -> bool:
      # Example: 8-16 hex characters
      if not card_id or len(card_id) < 8 or len(card_id) > 16:
          return False
      if not all(c in '0123456789ABCDEFabcdef' for c in card_id):
          return False
      return True
  ```
- Reject invalid card IDs with clear error message
- Sanitize card ID before logging (prevent log injection)
- Add configuration for card ID format validation rules
- Document expected card ID format in configuration

---

## [MEDIUM] Log Injection via Card ID

**Location**: Multiple locations where card_id is logged

**Risk**: Card IDs containing newlines or control characters can corrupt logs or inject fake log entries.

**Current Code**:
```python
logger.info(f"Processing attendance for card: {card_id[:8]}...")
logger.info(f"Card scanned in GUI: {card_id}")
logger.info(f"Queued attendance record (ID: {entry_id}, card: {card_id[:8]}...)")
```

**Potential Impact**:
- Log injection with fake log entries via newline characters
- Log parsing failures in SIEM/monitoring tools
- Security event masking by injecting benign-looking entries
- Compliance violations if logs are tampered
- Difficulty in incident investigation due to corrupted logs

**Recommended Fix Approach**:
- Implement log sanitization function:
  ```python
  def sanitize_for_log(value: str) -> str:
      # Remove newlines, carriage returns, tabs
      return value.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
  ```
- Apply sanitization to all user-controlled input in logs
- Use structured logging (JSON) which handles escaping automatically
- Configure logging formatter to escape special characters
- Add log integrity checking (signatures or hashes)

---

## [MEDIUM] No Validation on Configuration File Loading

**Location**: `src/config.py:158-174`

**Risk**: Configuration loaded from JSON file without validation, allowing arbitrary class attribute modification.

**Current Code**:
```python
@classmethod
def load_from_file(cls, config_file: str):
    if not os.path.exists(config_file):
        return

    with open(config_file, 'r') as f:
        config_data = json.load(f)

    # Update class attributes
    for key, value in config_data.items():
        if hasattr(cls, key):
            setattr(cls, key, value)
```

**Potential Impact**:
- Configuration file poisoning can modify any Config attribute
- Code execution through attribute manipulation (if Config has callable attributes)
- Security settings bypass (disable SSL verification, logging, etc.)
- Denial of service through malicious configuration values
- Path traversal via modified file paths

**Recommended Fix Approach**:
- Whitelist allowed configuration keys
- Validate each configuration value's type and range:
  ```python
  ALLOWED_CONFIG = {
      'API_BASE_URL': str,
      'SERIAL_PORT': str,
      'HTTP_TIMEOUT': (int, 1, 300),  # type, min, max
  }
  ```
- Implement schema validation using Pydantic or similar
- Reject configuration files with unknown keys (log warning)
- Add integrity check (signature) for configuration files
- Only allow trusted users to modify configuration files
- Document secure configuration file handling

---

## [MEDIUM] Command-Line Argument Injection via --config

**Location**: `datang_reader.py:337-349`

**Risk**: User-controlled config file path could lead to path traversal or unintended file access.

**Current Code**:
```python
parser.add_argument('--config', type=str,
                   help='Path to configuration file')
# ...
if args.config:
    Config.load_from_file(args.config)
```

**Potential Impact**:
- Path traversal to load arbitrary configuration files
- Information disclosure by loading sensitive files
- Configuration injection from untrusted sources
- Denial of service from malformed configuration files

**Recommended Fix Approach**:
- Validate config file path is within expected directory:
  ```python
  import os.path
  config_path = os.path.abspath(args.config)
  allowed_dir = os.path.abspath('/etc/datang-reader/')
  if not config_path.startswith(allowed_dir):
      raise ValueError("Config file must be in allowed directory")
  ```
- Whitelist allowed configuration file locations
- Check file ownership and permissions before loading
- Validate file extension (.json, .conf, etc.)
- Add documentation on secure configuration file placement
- Consider requiring configuration files to be root-owned on production

---

## [MEDIUM] Temperature Parameter Not Validated

**Location**: `src/service_manager.py:108`, `src/api_client.py:139`

**Risk**: Temperature parameter is not validated for reasonable range, allowing garbage values.

**Current Code**:
```python
def submit_attendance(
    self,
    card_id: str,
    timestamp: Optional[datetime] = None,
    temperature: Optional[float] = None
) -> Dict[str, Any]:
    # No validation of temperature value
    if temperature is not None and Config.ENABLE_TEMPERATURE:
        attendance_data["temperature"] = temperature
```

**Potential Impact**:
- Invalid temperature values sent to API
- Business logic errors from impossible temperatures
- Data integrity issues in attendance records
- API errors or rejection due to invalid data
- Potential for integer overflow or type confusion

**Recommended Fix Approach**:
- Define reasonable temperature ranges:
  ```python
  TEMP_MIN_CELSIUS = 30.0
  TEMP_MAX_CELSIUS = 45.0

  def validate_temperature(temp: float) -> bool:
      if temp < TEMP_MIN_CELSIUS or temp > TEMP_MAX_CELSIUS:
          raise ValueError(f"Temperature out of range: {temp}")
      return True
  ```
- Validate temperature before submission
- Convert between Celsius/Fahrenheit with validation
- Reject readings outside human physiological range
- Log suspicious temperature values for investigation
- Add configuration for temperature validation thresholds

---

## [LOW] No Validation on Timestamp Parameter

**Location**: `src/service_manager.py:119`

**Risk**: While timestamp is internally generated, if modified to accept external timestamps, no validation exists.

**Current Code**:
```python
timestamp = datetime.now()
# If externally provided, no validation of timestamp range
```

**Potential Impact**:
- Future timestamps could be submitted (time travel attacks)
- Very old timestamps could be replayed
- Timezone confusion causing incorrect attendance records
- API rejection due to unreasonable timestamps

**Recommended Fix Approach**:
- If accepting external timestamps, validate they are:
  - Not in the future (allow small clock skew, e.g., 5 minutes)
  - Not too far in the past (e.g., max 24 hours old)
  - In expected timezone or convert to UTC
- Add timestamp validation function:
  ```python
  def validate_timestamp(ts: datetime) -> bool:
      now = datetime.now()
      if ts > now + timedelta(minutes=5):
          raise ValueError("Timestamp in future")
      if ts < now - timedelta(hours=24):
          raise ValueError("Timestamp too old")
      return True
  ```
- Document timestamp handling and timezone requirements
- Consider using UTC internally for all timestamps

---

## [LOW] Pickle or Eval Risks (Currently None Found)

**Location**: Code review across all modules

**Risk Assessment**: No usage of `pickle`, `eval()`, `exec()`, or `__import__()` found in current codebase.

**Potential Impact**: None currently, but documenting for future development.

**Recommended Fix Approach**:
- Add code review checklist to prevent introduction of these functions
- Configure static analysis tools to flag dangerous functions
- Document banned functions in development guidelines
- Use JSON or Protocol Buffers for serialization instead of pickle
- If eval/exec needed, implement sandboxing with RestrictedPython
