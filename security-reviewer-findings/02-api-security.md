# API Security Issues

## [CRITICAL] Token Sent in Request Body Instead of Headers

**Location**: `src/api_client.py:164-173`

**Risk**: While documented as intentional, sending authentication tokens in request body violates security best practices and creates multiple vulnerabilities.

**Current Code**:
```python
# IMPORTANT: Token is sent in BODY, not in Authorization header!
attendance_data = {
    "version": Config.API_VERSION,
    "token": self.token,  # Token goes in request body
    "qr": None,
    "ic": None,
    "tag": card_id,
    "pid": None,
    "temperature": False
}
```

**Potential Impact**:
- Request body often logged by proxies, WAFs, and application logs
- Token visible in request dumps and debugging output
- Token may be cached by HTTP caching layers
- Violates OAuth 2.0 and industry standard authentication patterns
- Harder to implement proper token rotation and revocation
- Cannot use standard HTTP authentication middleware

**Recommended Fix Approach**:
- Work with API provider to support header-based authentication:
  - `Authorization: Bearer {token}` header
  - `X-API-Token: {token}` custom header
- If API cannot be changed, implement additional protections:
  - Never log request bodies
  - Use HTTPS with certificate pinning
  - Implement request signing to prevent token replay
  - Add timestamp to prevent replay attacks
- Document this as known technical debt requiring API changes

---

## [HIGH] No Request Timeout for Long-Running Requests

**Location**: `src/api_client.py:185-189`

**Risk**: While timeout is set, there's no check for hung connections or slow responses that could block the service.

**Current Code**:
```python
response = self.session.post(
    url,
    json=attendance_data,
    timeout=Config.HTTP_TIMEOUT  # 30 seconds
)
```

**Potential Impact**:
- Service hangs if API becomes unresponsive
- Resource exhaustion from accumulating hung connections
- Poor user experience with no feedback during timeouts
- Potential denial of service from malicious or misconfigured API

**Recommended Fix Approach**:
- Implement separate connect and read timeouts: `timeout=(5, 30)`
- Add circuit breaker pattern to stop calling failing API
- Implement async timeout handling to prevent blocking
- Add connection pooling limits to prevent resource exhaustion
- Log timeout events for monitoring and alerting
- Provide user feedback during timeout conditions

---

## [HIGH] No HTTPS Certificate Verification Enforced

**Location**: `src/api_client.py:49-53`

**Risk**: No explicit certificate verification configuration, relying on library defaults which may be insecure.

**Current Code**:
```python
self.session = requests.Session()
self.session.headers.update({
    'Content-Type': 'application/json',
    'User-Agent': 'Datang-Linux-Reader/1.0'
})
# No verify parameter set
```

**Potential Impact**:
- Man-in-the-middle attacks possible if defaults change
- No certificate pinning to prevent rogue CA attacks
- Self-signed certificate warnings may be ignored in production
- Traffic interception by proxies or malicious actors
- Credential and data exfiltration via MITM

**Recommended Fix Approach**:
- Explicitly set `verify=True` in all requests
- Implement certificate pinning for production API:
  ```python
  session.verify = '/path/to/api-certificate.pem'
  ```
- Add SSL/TLS verification testing in health checks
- Log certificate verification failures as CRITICAL
- Provide configuration option for custom CA certificates (corporate proxies)
- Never allow disabling verification in production

---

## [MEDIUM] No API Rate Limiting Protection

**Location**: `src/api_client.py:135-245` (entire client)

**Risk**: No client-side rate limiting to prevent API quota exhaustion or triggering server-side rate limits.

**Current Code**:
```python
# No rate limiting, backoff, or request throttling implemented
def submit_attendance(self, card_id: str, ...):
    response = self.session.post(url, ...)  # Direct call
```

**Potential Impact**:
- API quota exhaustion from rapid requests
- IP blocking if API has rate limits
- Service degradation from 429 (Too Many Requests) errors
- No graceful handling of rate limit responses
- Denial of service from queue synchronization storms

**Recommended Fix Approach**:
- Implement token bucket or leaky bucket rate limiter
- Add backoff on 429 responses using Retry-After header
- Limit queue sync batch size and add delays between requests
- Track request rate and warn when approaching limits
- Implement request queuing with prioritization (real-time vs sync)
- Add configuration for rate limit thresholds

---

## [MEDIUM] API Version Hardcoded Without Negotiation

**Location**: `src/config.py:23`

**Risk**: API version is hardcoded without capability to negotiate or support multiple versions.

**Current Code**:
```python
# API Version (sent in all requests)
API_VERSION = 1
```

**Potential Impact**:
- Breaking changes in API v2 cause application failure
- No backward compatibility support
- Cannot test against new API versions without code changes
- API deprecation notices cannot be handled gracefully
- Forced downtime during API upgrades

**Recommended Fix Approach**:
- Implement API version negotiation on connect
- Support multiple API versions with feature detection
- Add version compatibility matrix in configuration
- Parse API version from responses to detect mismatches
- Log warnings when API returns different version
- Provide graceful degradation for unsupported features

---

## [MEDIUM] Sensitive Error Messages Returned to User

**Location**: `src/api_client.py:122-126`, `232-237`

**Risk**: Detailed error messages including API responses are exposed to users, potentially leaking internal information.

**Current Code**:
```python
elif response.status_code == 401 or response.status_code == 403:
    logger.error(f"Authentication failed: {response.text}")
    raise AuthenticationError(f"Invalid credentials: {response.text}")
# ...
else:
    logger.error(f"Submission failed with status {response.status_code}: {response.text}")
    raise AttendanceSubmissionError(f"Server error: {response.text}")
```

**Potential Impact**:
- Internal API structure leaked through error messages
- Database errors or stack traces exposed to GUI users
- Information disclosure aids reconnaissance for attacks
- User confusion from technical error messages
- Sensitive data in error responses logged or displayed

**Recommended Fix Approach**:
- Implement error sanitization layer
- Map technical errors to user-friendly messages
- Log detailed errors server-side only
- Return generic errors to GUI: "Authentication failed" vs "Invalid credentials: [details]"
- Strip SQL errors, stack traces, and internal paths from user-facing errors
- Create error code system for support correlation without exposure

---

## [MEDIUM] No Request/Response Validation

**Location**: `src/api_client.py:196-223`

**Risk**: API responses are not validated against expected schema, allowing malformed or malicious responses.

**Current Code**:
```python
if response.status_code == 200 or response.status_code == 201:
    response_json = response.json()

    if "data" in response_json:
        data = response_json["data"]
        person_name = data.get("name", "Unknown")  # No validation
```

**Potential Impact**:
- Application crashes from unexpected response structure
- Type confusion vulnerabilities from wrong data types
- XSS or injection if response data displayed without sanitization
- Logic errors from missing required fields
- Security bypass from manipulated response fields

**Recommended Fix Approach**:
- Implement response schema validation using Pydantic or similar
- Define expected response models for each endpoint
- Validate all required fields exist and have correct types
- Reject responses that don't match schema
- Sanitize all response data before use or display
- Add integration tests with malformed response handling

---

## [LOW] User-Agent String Reveals Implementation Details

**Location**: `src/api_client.py:52`

**Risk**: User-Agent reveals specific platform details that could aid reconnaissance.

**Current Code**:
```python
'User-Agent': 'Datang-Linux-Reader/1.0'
```

**Potential Impact**:
- Attackers can identify vulnerable versions
- Platform-specific exploits can be targeted
- Reveals deployment architecture details
- Aids fingerprinting for automated attacks

**Recommended Fix Approach**:
- Use generic User-Agent: "Datang-Reader/1.0"
- Add platform only if required by API
- Implement version negotiation without revealing exact version
- Consider rotating User-Agent strings
- Document User-Agent policy in security guidelines

---

## [LOW] No Connection Pooling Limits

**Location**: `src/api_client.py:49`

**Risk**: Default session configuration may allow unlimited connections, causing resource exhaustion.

**Current Code**:
```python
self.session = requests.Session()
# No connection pool configuration
```

**Potential Impact**:
- Socket exhaustion from too many connections
- Memory leaks from unclosed connections
- Port exhaustion on client system
- Degraded performance from connection overhead

**Recommended Fix Approach**:
- Configure connection pool size:
  ```python
  adapter = HTTPAdapter(
      pool_connections=10,
      pool_maxsize=20,
      max_retries=3
  )
  session.mount('https://', adapter)
  ```
- Set connection timeout for idle connections
- Implement connection cleanup on service stop
- Monitor connection pool metrics
- Document connection limits in configuration
