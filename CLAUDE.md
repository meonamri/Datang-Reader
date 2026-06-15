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
- **Mark (DOM-level, no submit): VALIDATED live** against the real attendance
  table. `form_filler.mark_student_absent` unchecks the student, selects
  category PONTENG, and sets reason **N0040027 / MALAS KE SEKOLAH** on the
  correct `select.selectsebab` element (verified by reading back
  `sebab.value == 'N0040027'`). No Kemaskini/Simpan was clicked, so nothing was
  persisted. See "Reason-targeting fix" below.
- **Reason mapping VALIDATED:** all 12 `MOEIS_CATEGORIES` and all 5 PONTENG (N)
  `COMPLETE_MOEIS_SEBAB` codes match the live portal dropdowns text-for-text,
  and the portal's option `value` *is* the sebab code (e.g. `value="N0040027"`).
- **Submit (`form_filler.mark_absences_and_submit` → `_submit_form`): STILL
  UNTESTED and not to be run casually** — the Kemaskini → Simpan & Sahkan → OK
  flow writes REAL absence records to a live government portal. Hard to reverse.
  (Note: the submit AJAX endpoints `kemaskiniKehadiranHarian` / `sahkanharian*`
  are also hardcoded `http://` and depend on the same CSRF-preserving fix below
  to ever succeed.)

### Reason-targeting fix in `form_filler.py` (this session)

The attendance row contains **three** `<select>`s: two `kategori[]`
(`select.selectkategori`, one a Select2 duplicate) and — appended lazily only
*after* a category is chosen — one `sebabcuti[]` (`select.selectsebab`).
`mark_student_absent` previously grabbed the reason dropdown as
`row.querySelectorAll('select')[1]`, which is the **second category** select,
not the reason select — so the reason was never set and the function returned
`success` with only a warning (it would have submitted absences with no reason).
Fixed to: select the category via `select.selectkategori`, then **poll/re-query
for `select.selectsebab`** and set the reason there; a missing reason is now a
hard failure (`success: false`) instead of a silent warning.

### Submit-path audit (2026-06-15, READ-ONLY — nothing submitted)

Audited via `diag_idme_reasons.py --audit-submit` (dumps buttons + their bound
jQuery handlers + greps page scripts for the submit endpoints; never clicks a
submit control). Findings — **`_submit_form` is currently broken and must be
rewritten before any live submit:**

- **The "Simpan & Sahkan" selector is wrong.** Clicking **Kemaskini**
  (`button#kemaskiniKehadiran`, text "Kemaskini" — step 1 is fine) does NOT
  submit; its handler builds a confirmation modal *client-side* with three
  buttons: **Batal** (`.batal`), **Simpan** (`.simpan`), and **Sahkan**
  (`.simpansah`, green). The literal text **"Simpan & Sahkan" only appears as a
  DISABLED button** (shown when `layaksahkan` is false). So `_submit_form`'s
  `button:has-text("Simpan & Sahkan")` either times out or clicks a disabled
  no-op — i.e. it would report success while submitting nothing. The real
  confirm control is **`.simpansah`** (text "Sahkan").
- **Draft vs confirm (reversibility lever).** `.simpan` → `kemaskini('simpan')`
  saves a **draft** (status MENUNGGU PENGESAHAN, re-editable); `.simpansah` →
  `kemaskini('simpansah')` **confirms** (TELAH DISAHKAN, the hard-to-reverse
  one). A safer first live test = the `.simpan` draft path, not `.simpansah`.
- **Step 3 "OK" button** likely doesn't exist — feedback is SweetAlert (Ya/Tidak
  confirm). The current `try/except` around it already swallows the miss.
- **CSRF prefilter DOES cover submit.** `kemaskini(statussimpan)` posts via
  `$.ajax` to `http://moeispel.moe.gov.my/sahsiah/kehadiran/tabguru/kemaskiniKehadiranHarian`
  — jQuery AJAX, so the `login_engine` http→https `ajaxPrefilter` rewrites it
  (no native `fetch`, which the prefilter would miss). The `tabguru` daily
  submit is the relevant endpoint; the `pkhem/sahkanharian*` endpoints are a
  *separate* monthly-confirmation flow, not the teacher daily submit.

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
- `server/diag_idme_reasons.py` — diagnostic that dumps the live portal's
  category + PONTENG reason dropdowns and diffs them against `moeis_codes.py`
  (no PII printed). Default run is read-only. `--validate-mark` additionally
  exercises `form_filler.mark_student_absent` on ONE student and reads back the
  selected `select.selectsebab` value — it unchecks a checkbox + sets dropdowns
  in the live DOM but **never clicks Kemaskini/Simpan, so nothing is submitted**.
  Gitignored. Run: `.\.venv-idme\Scripts\python.exe diag_idme_reasons.py --headless [--validate-mark]`.
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
