# CLAUDE.md — `idme-integration` branch

> ⚠️ **THIS BRANCH IS IN ACTIVE TESTING — NOT PRODUCTION-READY.**
> This file is branch-specific to `idme-integration`. `main` has no CLAUDE.md.
> When this branch is eventually merged into `main`, **remove or rewrite this
> testing banner** (a committed file carries over on merge; git cannot pin a
> file to a branch permanently).

## What this branch adds

The **IDME module** (`server/src/idme/`): automated absence submission to
Malaysia's IDME/MOEIS portal. At a daily cutoff time it computes
`roster − RFID scans = absent students`, logs into `idme.moe.gov.my` via
Playwright/Firefox, fills the MOEIS attendance form, and submits.

Plus (commit `4cbc2c9`) roster Excel upload with replace option + template download.

## Current testing status (2026-06-15)

- **Login + navigation + student-table read: VALIDATED end-to-end against the
  live portal** (with valid teacher credentials; no 2FA/OTP). All 6 login steps
  pass, SSO into MOEIS works, CSRF + cookies extract, and
  `form_filler.get_student_list` returns the real class roster (25 students for
  the test teacher's class). Reproduced over multiple consecutive headless runs.
- **Mark + submit (`form_filler.mark_absences_and_submit`): STILL UNTESTED and
  not to be run casually** — it submits REAL absence records to a live
  government portal. Hard to reverse. (Note: the submit AJAX endpoints
  `kemaskiniKehadiranHarian` / `sahkanharian*` are also hardcoded `http://` and
  depend on the same CSRF-preserving fix below to ever succeed.)

### Engine changes made this session (for the eventual merge review)

All in `login_engine.py`, required to reach the attendance table on the live
portal. The MOEIS portal hardcodes `http://` URLs but only serves `https`
(port 80 is closed), which broke the automation in three distinct ways:

1. **`dom.security.https_only_mode = True`** added to `firefox_user_prefs`
   (alongside the HTTP/2-disabled prefs). The SSO step redirects to
   `http://moeispel…` → `NS_ERROR_CONNECTION_REFUSED` without this; it forces
   the http→https upgrade (the automated equivalent of manually adding the "s").
2. **`networkidle` → `domcontentloaded`** for all 5 waits/navigations. The
   MOEIS pages never reach `networkidle` (perpetual dashboard polling), so the
   old waits timed out.
3. **`step4` restructured**: after the SSO hop establishes the session, the
   attendance page is opened on a **fresh page in the same context** (the
   moeispel home document never settles; navigating away from it raises
   `NS_ERROR_FAILURE`). On that page we inject a **jQuery `$.ajaxPrefilter`**
   that rewrites `http://moeispel`→`https://` *before* requests are sent
   (the cross-scheme 307 strips the `X-CSRF-TOKEN` header → HTTP 419 / empty
   table), then trigger the class-select `change` event to load the rows.
   `self.page` is reassigned to this attendance page so steps 5/6 + form_filler
   operate on it.

## Local test harness (not part of the Docker app)

For manual Playwright testing. **This machine is Windows** (the venv was rebuilt
here; the activate path is `Scripts\`, not `bin/`). On Windows, invoke the venv
python directly rather than activating:

- `server/.venv-idme/` — isolated venv (Playwright 1.60 + Firefox). Gitignored.
- `server/test_idme_login.py` — **read-only** driver: login → navigate → read
  student list. Does NOT mark or submit. Run (Windows):
  ```powershell
  cd server
  .\.venv-idme\Scripts\python.exe test_idme_login.py             # visible
  .\.venv-idme\Scripts\python.exe test_idme_login.py --headless  # no window
  ```
- `server/diag_idme_attendance.py` — **read-only** diagnostic used to reverse-
  engineer the attendance-page navigation/AJAX issues (dumps page state to
  `server/idme-diag/`). Gitignored. Its `idme-diag/` dumps contain **real
  student PII** — never commit them.
- `server/.idme-test.env` — teacher IC + password for the test (gitignored;
  copy from `.idme-test.env.example`). Never commit real credentials.

All gitignored (see `.gitignore` → "IDME local test harness").

## Notes / known issues

- `login_engine.py:421` logs the teacher IC at INFO level — leaks it into test
  output. Consider masking before sharing logs.
- Debug screenshots target `/data/idme/screenshots` (a Docker path) — won't
  exist on a dev Mac; screenshots silently skip unless that path is writable.
- Firefox with HTTP/2 disabled is **required** for Malaysian gov portals — do
  not "simplify" that out of `login_engine._initialize_browser`.
- Real end-to-end needs: Docker, `server/.env` (with `IDME_ENABLED=true` +
  `IDME_ENCRYPTION_KEY`), teachers added via `/idme/settings`, and a roster
  imported. None of that is set up on this machine.

See `README.md` § "IDME Module" for the full architecture and API endpoints.
