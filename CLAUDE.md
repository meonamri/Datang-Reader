# CLAUDE.md — `idme-integration` branch

> ⚠️ **THIS BRANCH IS IN ACTIVE TESTING — NOT PRODUCTION-READY.**
> This file is branch-specific to `idme-integration`. `main` has no CLAUDE.md.
> When this branch is eventually merged into `main`, **remove or rewrite this
> testing banner** (a committed file carries over on merge; git cannot pin a
> file to a branch permanently).

## NEXT STEP (handoff — read me first, 2026-06-15)

We finished the **design phase** for student identity resolution and stopped
**right before starting Phase 1**. Pick up there.

- **Read first:** `server/src/idme/IDENTITY_RESOLUTION_DESIGN.md` (the agreed
  plan). It supersedes ad-hoc name matching with: a persistent identity registry
  seeded from the portal, **passively-learned RFID tags** from the scan stream,
  mark-by-`idpelajar` for form-filling, and a settings-UI tag-coverage panel.
- **Settled facts (don't re-investigate):** IC is **unavailable on both sides**
  (Datang response has no IC; portal row exposes only `data-idpelajar` +
  `data-namapelajar` — confirmed via `diag_idme_pipeline.py --probe-portal-attrs`).
  So name is the only scan↔roster bridge; RFID tag is the daily key once learned.
- **Phase 1 (START HERE):** harden `absence_detector._normalize_name` (currently
  only uppercases + collapses spaces; docstring's "bin/binti" claim is FALSE —
  see Notes/known issues) AND add the variant cases as assertions in
  `server/diag_idme_pipeline.py`. Calibration caveat: a false *present* (two
  students collapsing to one) is worse than a false absent — when fuzzy is
  ambiguous, prefer no-match + alert over a guess.
- Phases 2 (portal "Initialise Roster" + mark-by-idpelajar) and 3 (tag learning +
  tag-first detection + coverage UI) follow — see the design doc's phased plan.

## What this branch adds

The **IDME module** (`server/src/idme/`): automated absence submission to
Malaysia's IDME/MOEIS portal. At a daily cutoff time it computes
`roster − RFID scans = absent students`, logs into `idme.moe.gov.my` via
Playwright/Firefox, fills the MOEIS attendance form, and submits.

Plus (commit `4cbc2c9`) roster Excel upload with replace option + template download.

## Current testing status (2026-06-15)

- **Offline data pipeline (absence detection + credential round-trip):
  VALIDATED** via `diag_idme_pipeline.py` against the *real* 25-student roster
  (pulled read-only from the portal) seeded into a throwaway `idme_data.db`.
  `AbsenceDetector.detect_absences` computes `roster − scans = absent` correctly,
  emits dicts whose shape (`student_name`/`category`/`sebab_id`) feeds
  `form_filler.mark_absences_and_submit` unchanged, and `CredentialManager`
  Fernet encrypt/decrypt round-trips (wrong key → `DecryptionError`). **Caveat
  surfaced:** `absence_detector._normalize_name` only uppercases + collapses
  spaces — its docstring claim of "handle bin/binti variations" is FALSE. Scan
  names that differ structurally from the roster (BIN↔B., BINTI↔BT, appended
  titles/aliases) are NOT matched, so a *present* student gets FALSELY marked
  absent. Whitespace/case variants are fine. **Harden the normalizer before any
  live orchestrator run** (see Notes / known issues).
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
- **Submit (`form_filler._submit_form`): VALIDATED live end-to-end 2026-06-15**
  (with explicit user authorization; the test class was left CONFIRMED and the
  user reset it afterward). After the `_submit_form` rewrite (see "Submit-path
  rewrite" below): the **draft** path (`.simpan`) produced status **MENUNGGU
  PENGESAHAN**, and the **confirm** path (`.simpansah`) produced **TELAH
  DISAHKAN**, which persisted across a fresh login. The submit AJAX
  (`kemaskiniKehadiranHarian`) fired through the http→https `ajaxPrefilter`
  successfully (no 419). **Still writes REAL records — do not run casually.**
  Known limitation: `_submit_form`'s status read-back is best-effort (the portal
  updates the badge asynchronously; the function now waits for the *expected*
  status string but may still mis-read if the portal only refreshes on reload —
  the submit itself is unaffected).

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

### Submit-path rewrite in `form_filler.py` (2026-06-15, then LIVE-VALIDATED)

`_submit_form` rewritten per the audit and the live test:

- **New signature `_submit_form(confirm: bool = True)`** (threaded through
  `mark_absences_and_submit(..., confirm=True)`). `confirm=True` clicks
  `.simpansah` (Sahkan → TELAH DISAHKAN, production); `confirm=False` clicks
  `.simpan` (Simpan → MENUNGGU PENGESAHAN, re-editable draft). Returns the
  detected **status string** ('' on failure) instead of a bare bool;
  `mark_absences_and_submit` now also returns `status`.
- **Clicks fire via jQuery `.trigger('click')` inside `page.evaluate`, NOT
  Playwright `.click()`** — the portal shows a `.loadover` overlay that
  intercepts pointer events and hangs actionability-based clicks (observed: a
  30s timeout on `#kemaskiniKehadiran`). Triggering the bound handler directly
  is reliable (same pattern as the dropdown code). Kemaskini opens a SweetAlert
  modal; we poll for `.simpan`/`.simpansah` to be in the DOM, then trigger it.
- **Status verification is best-effort.** It waits for the *expected* status
  string to appear (so a just-confirmed day isn't misread as the prior
  MENUNGGU), but the portal may only refresh the badge on reload, so the
  read-back can still lag. The submit action itself is unaffected.
- A **confirmed day (TELAH DISAHKAN) locks the form** — re-running submit on it
  is a no-op (no AJAX fires). To re-test the draft→confirm transition the day
  must first be reset in the portal.
- Exercised by `diag_idme_reasons.py --do-submit` (draft then confirm; captures
  the `kemaskiniKehadiranHarian` POST + dumps the dialog/status each phase).

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
- `server/diag_idme_pipeline.py` — **offline** pipeline diagnostic for the
  untested data half (absence detection + Fernet round-trip). Pulls the real
  roster **read-only** (`--refresh-roster`, caches to gitignored
  `server/idme-pipeline/roster.json`), then seeds a throwaway
  `idme-pipeline/pipeline_test.db` and runs `AbsenceDetector` against synthesized
  scans incl. mangled name variants. **Never logs in for marking; never submits.**
  Names are masked in console output (no PII printed). Run:
  `.\.venv-idme\Scripts\python.exe diag_idme_pipeline.py [--refresh-roster --headless]`
  (omit `--refresh-roster` to reuse the cached roster, fully offline).
- `server/.idme-test.env` — teacher IC + password for the test (gitignored;
  copy from `.idme-test.env.example`). Never commit real credentials.

All gitignored (see `.gitignore` → "IDME local test harness"); `idme-pipeline/`
holds the cached real roster + temp DB and is also gitignored.

## Notes / known issues

- **`absence_detector._normalize_name` is too weak (BUG, found 2026-06-15).** It
  only `.upper()`s + collapses double-spaces, but its docstring claims it
  "handle[s] bin/binti variations" — it does not. If the school-Excel roster name
  and the Datang-API scan name for the *same* student differ structurally
  (BIN↔B./BINTI↔BT, appended titles, `@` aliases, token reordering), the diff
  treats the present student as absent and would submit a real false absence.
  Must be hardened (token-set comparison, bin/binti canonicalization) before the
  live orchestrator run. Reproduced by `diag_idme_pipeline.py`.
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
