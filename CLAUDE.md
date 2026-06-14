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

- **Login automation (`login_engine.py`): VALIDATED against the live portal.**
  All 6 login steps and selectors fire correctly; no 2FA/OTP appeared.
  Last test run failed only on **invalid credentials** ("No Kad Pengenalan dan
  kata laluan tidak sepadan"), not on automation logic. Re-test pending valid
  teacher IC + password.
- **Student-table read (`form_filler.get_student_list`): not yet confirmed**
  (blocked behind a successful login).
- **Mark + submit (`form_filler.mark_absences_and_submit`): UNTESTED and not to
  be run casually** — it submits REAL absence records to a live government
  portal. Hard to reverse.

## Local test harness (not part of the Docker app)

Created for manual Playwright testing on this machine (macOS, no Docker):

- `server/.venv-idme/` — isolated venv (Playwright 1.60 + Firefox). Gitignored.
- `server/test_idme_login.py` — **read-only** driver: login → navigate → read
  student list. Does NOT mark or submit. Run:
  ```bash
  cd server && . .venv-idme/bin/activate && python test_idme_login.py      # visible
  python test_idme_login.py --headless                                      # no window
  ```
- `server/.idme-test.env` — teacher IC + password for the test (gitignored;
  copy from `.idme-test.env.example`). Never commit real credentials.

All three are gitignored (see `.gitignore` → "IDME local test harness").

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
