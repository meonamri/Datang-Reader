# Authentication Security Issues

## [CRITICAL] Hardcoded Credentials in Source Code ✅ FIXED

**Status**: ✅ **RESOLVED** (2025-11-06)

**Location**: `src/config.py:40-41`

**Risk**: Hardcoded credentials in source code represent a critical security vulnerability. These credentials are committed to version control, making them accessible to anyone with repository access.

**Current Code**:
```python
READER_USERNAME = os.getenv("DATANG_READER_USERNAME", "30370_reader78")
READER_PASSWORD = os.getenv("DATANG_READER_PASSWORD", "30370_reader78_zb39")
```

**Potential Impact**:
- Credentials exposed in Git history (visible to all with repo access)
- Credentials visible in logs if config is dumped
- Credentials accessible to anyone who can read the source code
- If repo becomes public or is leaked, credentials are immediately compromised
- Cannot rotate credentials without code changes

**Recommended Fix Approach**:
- Remove default credential values entirely
- Force credentials to be set via environment variables or secure config file
- Add validation that fails fast if credentials are not provided
- Document secure credential management in README
- Consider using a secrets management service (AWS Secrets Manager, HashiCorp Vault, etc.)

**Resolution Implemented** (2025-11-06):
✅ Removed all hardcoded credential defaults from `src/config.py:40-41`
✅ Changed to: `READER_USERNAME = os.getenv("DATANG_READER_USERNAME")`
✅ Changed to: `READER_PASSWORD = os.getenv("DATANG_READER_PASSWORD")`
✅ Added fail-fast validation in `Config.validate()` with clear error messages
✅ Updated README.md with platform-specific instructions (Linux/macOS/Windows)
✅ Updated install.sh to guide users on setting environment variables
✅ Added security notices throughout documentation
✅ Updated CONFIG_TEMPLATE to prevent credential storage in config files

**Verification**:
- Application now fails immediately on startup if credentials not set
- Error message provides clear guidance: "Set the DATANG_READER_USERNAME environment variable..."
- No credentials remain in source code or Git history (post-remediation)
- Documentation covers all deployment scenarios (systemd, Docker, manual)

---

## [HIGH] Token File Permissions Not Enforced on Windows

**Location**: `src/auth_manager.py:109-113`

**Risk**: Token file permissions cannot be set properly on Windows, leaving tokens readable by all users on the system.

**Current Code**:
```python
# Set restrictive permissions (readable only by owner)
try:
    os.chmod(self.token_file, 0o600)
except (OSError, TypeError):
    # Windows doesn't support Unix permissions
    logger.debug("File permissions not set (Windows/non-Unix platform)")
```

**Potential Impact**:
- On Windows, token files are created with default permissions (readable by all local users)
- Local privilege escalation possible if attacker gains access to user's filesystem
- Multi-user systems expose tokens to other users
- No warning to administrator about security implications

**Recommended Fix Approach**:
- Use Windows ACLs via `win32security` module when on Windows
- Set file to be readable only by current user and SYSTEM
- Log a WARNING (not DEBUG) when permissions cannot be set
- Provide documentation on manual permission hardening for Windows
- Consider encrypting token file contents on Windows as additional layer

---

## [HIGH] No Token Expiration Validation

**Location**: `src/auth_manager.py:61-65`

**Risk**: Saved tokens are loaded without validation of expiration time, potentially using expired tokens.

**Current Code**:
```python
# Check token age (optional - if you know token lifetime)
if saved_at:
    token_age = datetime.now() - datetime.fromisoformat(saved_at)
    logger.debug(f"Token age: {token_age}")
    # You might want to check if token is too old here
```

**Potential Impact**:
- Application attempts to use expired tokens
- Unnecessary API calls that will fail with 401 errors
- Poor user experience with repeated authentication failures
- Token reuse beyond intended lifetime if API doesn't enforce expiration

**Recommended Fix Approach**:
- Implement token expiration check based on saved_at timestamp
- Define TOKEN_LIFETIME in Config (e.g., 24 hours, 7 days)
- Reject tokens older than TOKEN_LIFETIME
- Force re-authentication when token is expired
- Add token refresh mechanism if API supports it

---

## [MEDIUM] Token Logged in Debug Output

**Location**: `src/api_client.py:98-100`

**Risk**: API responses (which may contain tokens) are logged at DEBUG level, potentially exposing tokens in log files.

**Current Code**:
```python
# Log response for debugging
logger.debug(f"Response status: {response.status_code}")
logger.debug(f"Response body: {response.text[:200]}")
```

**Potential Impact**:
- Tokens visible in log files when DEBUG logging is enabled
- Log files may be readable by other users or backed up insecurely
- Tokens may be transmitted to log aggregation services
- Credentials exposure if logs are shared for troubleshooting

**Recommended Fix Approach**:
- Implement response sanitization function to redact sensitive fields
- Never log full response body - log only non-sensitive metadata
- Redact "token", "password", "api_key" fields before logging
- Consider using structured logging with automatic PII redaction
- Document that DEBUG mode should never be used in production

---

## [MEDIUM] No Secure Token Storage (Plaintext JSON)

**Location**: `src/auth_manager.py:89-106`

**Risk**: Authentication tokens are stored in plaintext JSON files on disk.

**Current Code**:
```python
data = {
    'token': token,
    'saved_at': datetime.now().isoformat(),
    'device_id': Config.DEVICE_ID
}

# Write token file
with open(self.token_file, 'w') as f:
    json.dump(data, f, indent=2)
```

**Potential Impact**:
- Token readable by any process running as the user
- Token accessible if system is compromised
- Token visible in backups and file system forensics
- Token not protected if disk is physically stolen (unless full-disk encryption)

**Recommended Fix Approach**:
- Encrypt token before storing using system keyring/credential manager:
  - Linux: Use `keyring` library with SecretService backend
  - Windows: Use Windows Credential Manager via `win32cred`
  - macOS: Use Keychain via `keyring`
- Fallback to encrypted file if system keyring unavailable
- Use AES-256 encryption with machine-specific key derived from hardware identifiers
- Add integrity check (HMAC) to detect tampering
- Document security properties of token storage

---

## [MEDIUM] No Account Lockout Protection

**Location**: `src/api_client.py:57-133`

**Risk**: No rate limiting or backoff on failed authentication attempts, enabling brute force attacks.

**Current Code**:
```python
def login(self, username: Optional[str] = None, password: Optional[str] = None) -> str:
    # ... no retry limits, no backoff, immediate retry possible
```

**Potential Impact**:
- Brute force attacks possible against API
- Account compromise through credential stuffing
- No protection against automated authentication attempts
- API could be overwhelmed with login requests

**Recommended Fix Approach**:
- Implement exponential backoff after failed login attempts
- Add max retry counter (e.g., 3 attempts, then wait 5 minutes)
- Store failed attempt count in persistent state
- Log failed authentication attempts for security monitoring
- Add CAPTCHA or challenge-response after multiple failures (if API supports)
- Consider implementing client-side rate limiting

---

## [LOW] Device ID Not Validated as Unique

**Location**: `src/config.py:44`

**Risk**: Default device ID "linux-reader-001" may be shared across multiple installations, preventing proper device-specific authentication.

**Current Code**:
```python
DEVICE_ID = os.getenv("DATANG_DEVICE_ID", "linux-reader-001")
```

**Potential Impact**:
- Multiple devices using same device ID
- Inability to track specific device activity
- Token intended for one device usable on another
- Audit logs cannot distinguish between devices

**Recommended Fix Approach**:
- Generate unique device ID on first run based on:
  - Machine UUID from DMI/SMBIOS
  - MAC address hash
  - Random UUID stored persistently
- Store generated device ID in config file or system location
- Validate device ID format and uniqueness
- Prompt user to set custom device ID during installation
- Document importance of unique device IDs per installation
