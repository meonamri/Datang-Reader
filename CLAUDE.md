# CLAUDE.md — `idme-integration` branch

> ⚠️ **THIS BRANCH IS IN ACTIVE TESTING — NOT PRODUCTION-READY.**
> This file is branch-specific to `idme-integration`. `main` has no CLAUDE.md.
> When this branch is eventually merged into `main`, **remove or rewrite this
> testing banner** (a committed file carries over on merge; git cannot pin a
> file to a branch permanently).

## NEXT STEP (handoff — read me first, updated 2026-06-15 PM)

**WHERE WE'RE AT: the engine is fully proven end-to-end; the NEXT STEP is the
PRODUCTION ROLLOUT, which the user will drive with a FRESH Claude instance.**
Read the "PROD ROLLOUT PLAN" block just below — that's your job if you're that
new instance.

Full container e2e was validated **live on the Pi** 2026-06-15 PM via the **real
`Orchestrator.submit_class` path** (not the diag script): `/card` scan → Datang
resolve → `record_scan` → tag-learning (coverage 0→25/25 for class "3 USM") →
`detect_absences` → live login → mark-by-idpelajar → submit. **Both** paths hit
the live portal: draft (`confirm=false`) → MENUNGGU PENGESAHAN, confirm
(`confirm=true`) → TELAH DISAHKAN. Any future live submit still needs fresh
user authorization each time — do NOT run it casually or autonomously.

**TWO BUGS found during this live e2e and FIXED + PUSHED to `idme-integration`:**
- **`cb9c68d`** — the IDME scan hook NEVER recorded. `api_client.submit_attendance()`
  returns the *unwrapped* student dict (`{name,section,pid,...}`), but
  `service_manager.process_attendance` gated on `response.get("data")` (a key that
  never exists) → `record_scan` never called → `daily_scans` empty → absence
  detector would mark the WHOLE roster absent → scheduler would submit everyone
  absent. Fixed via shared `_record_idme_scan()` (pass `response` directly, gate
  on `name`), called on the main AND token-refresh-retry paths.
- **`19182fd`** — the offline-queue `/sync` path (`offline_queue.sync_with_api`)
  submitted queued scans to Datang but never fed them to the IDME tracker (same
  bug class, one layer over). Fixed with an optional `on_synced(card_id, response)`
  callback wired to `_record_idme_scan` from `ServiceManager.sync_queue`. Verified
  on the container (enqueue → `/sync` → `daily_scans` row appears).

**PROD ROLLOUT PLAN (the actual NEXT STEP):**
IDME is NOT a separate service — it's a module inside the same `datang-reader`
image/container. Rolling out = an *in-place upgrade* of the prod `datang-reader`
container (host port **8081**, project dir `~/Datang-Reader/server`, project name
`server`): rebuild from merged code + `docker compose up -d` recreates the SAME
8081 container with IDME enabled. Datang scanning for every student is unchanged;
the only new behavior is MOEIS submission for *onboarded* classes. **Scope is
opt-in per teacher:** `submit_all_classes` iterates configured teachers only, so
classes WITHOUT a teacher are never submitted to MOEIS (Datang-only, as today).
The user currently has **2 teachers' credentials** → only those 2 classes would
be automated; onboard the rest gradually.
Rollout checklist:
  1. **Merge `idme-integration` → `main`** and REMOVE the testing banner at the
     top of this file (it carries over on merge). Merging with `IDME_ENABLED=false`
     is safe/dormant (gated, additive, `_record_idme_scan` no-ops when
     `scan_tracker` is None).
  2. **Prod `.env`** (`~/Datang-Reader/server/.env`): add `IDME_ENABLED=true`,
     `IDME_ENCRYPTION_KEY=<FRESH Fernet key — generate prod its OWN, don't reuse
     test>` (`server/gen_fernet_key.py`), `IDME_CUTOFF_TIME=HH:MM`.
  3. **Prod volume**: the merged compose adds `../docker-data/idme:/data/idme`
     (prod's current mounts DON'T have it). Pre-create `~/Datang-Reader/docker-data/idme`.
     Also ensure `queue.db`/`token` bind sources stay FILES (Docker auto-creates
     missing bind sources as DIRS → sqlite "unable to open database file"); prod
     already has them as files.
  4. **Recreate** the 8081 container; add teachers via `/idme/settings`; init
     roster per class. **Class string must match across 3 places** (roster Class
     / Datang scan `section` / teacher `class_name`) or a class silently misfires.
  5. **TURN-ON IS GATED — do NOT trust unattended auto-confirm yet.** The
     scheduler's `submit_all_classes`→`submit_class` HARD-DEFAULTS `confirm=True`
     (auto-confirms LOCKED TELAH DISAHKAN daily, unattended). RECOMMENDED before
     any unattended run: (a) make the scheduler submit DRAFTS (`confirm=False`) for
     a supervised period so a human confirms each morning — this is a SMALL code
     change, NOT yet done; (b) observe ONE real scheduled fire end-to-end (every
     submit so far was a MANUAL `/idme/submit`); (c) per-class roster/name
     alignment + `no_match`/coverage review. Name-mismatch = a student absent EVERY
     day (a `no_match` never learns a tag).

**OPEN CLEANUP (from the e2e session):** the test left a CONFIRMED (locked) false
absence for **AHMAD DANISH RYAN BIN HASNUL FAIZ** in class "3 USM" on the live
MOEIS portal — the user said they would reset it (verify it's cleared). The
throwaway test deployment (`~/test build`, compose project `datangtest`, port
8082, image `datang-reader:testbuild`) was TORN DOWN; its data dir
`~/test build/docker-data` persists if you want to bring it back
(`docker compose -p datangtest up -d` — ALWAYS pass `-p datangtest`: both prod and
test compose dirs are named `server`, so a bare `up` collides and recreates the
PROD container).

**Older milestone (still true):** the identity-resolution design — all 3 phases —
is IMPLEMENTED (see `server/src/idme/IDENTITY_RESOLUTION_DESIGN.md`); offline +
live read-only validation green. History below.

- **Phase 1 DONE (commit `43169e0`):** `_normalize_name` hardened — bin/binti
  canonicalization (`B.`/`BN`→BIN, `BT`/`BTE`/`BTI`→BINTI, medial-only),
  parenthetical/bracket strip, `@`-spacing. Extracted into shared
  `idme/names.py`. Deliberately conservative: **no token-sort** (collision risk).
  `detect_absences`/`get_attendance_summary` now iterate the roster directly
  (fixes the silent dict-overwrite vanish bug) + `_warn_on_collisions`.
- **Phase 2 DONE (commit `20755a9`):** `idme/migrations.py` (idempotent ALTER ADD
  COLUMN for existing DBs) adds `idpelajar`/`tag_source`/`tag_updated_at`/`source`
  + `unmatched_scans` table. `RosterManager.upsert_from_portal` (registry seeded
  from portal, keyed on idpelajar/(name,class), preserves learned tags).
  `form_filler.mark_student_absent` marks by **`data-idpelajar`** with name
  fallback. `Orchestrator.init_roster_from_portal` + `POST /idme/roster/init` +
  a settings-UI "Initialise Roster from Portal" button. **Live-validated
  read-only**: idpelajar locates+marks a student with a bogus name (Seam B),
  no submit.
- **Phase 3 DONE (commit `c8dd72c`):** `scan_tracker.record_scan` passively learns the
  RFID tag onto the matching student (overwrites on card replacement; logs
  `unmatched_scans` on no-match/ambiguous). `absence_detector._is_present` is
  **tag-first, name-fallback** (daily op is name-free once tags are learned).
  `GET /idme/roster/coverage` + settings-UI "RFID Tag Coverage" panel
  (mapped/total per class, unmapped list, unmatched/ambiguous counts).
- **Settled facts (don't re-investigate):** IC is **unavailable on both sides**
  (Datang response has no IC; portal row exposes only `data-idpelajar` +
  `data-namapelajar`). Name bridges init + first-scan + card-replacement; RFID
  tag is the daily key once learned.
- **Live submit VALIDATED (2026-06-15, user-authorized):** marked one student by
  `idpelajar` then `diag_idme_reasons.py --do-submit` (its `mark_one_checked` now
  passes name+idpelajar like production). Draft → MENUNGGU PENGESAHAN; confirm →
  TELAH DISAHKAN (`kemaskiniKehadiranHarian` POST = 200). The full
  detect→mark-by-idpelajar→confirm flow is proven live. Remaining nice-to-haves
  (not blocking): a true orchestrator end-to-end run needs a configured teacher +
  imported roster in `idme_data.db` (none set up on this dev machine); the open
  questions in the design doc §11 (serial logins at scale, secret surface) are
  pre-rollout hardening, not correctness.

## What this branch adds

The **IDME module** (`server/src/idme/`): automated absence submission to
Malaysia's IDME/MOEIS portal. At a daily cutoff time it computes
`roster − RFID scans = absent students`, logs into `idme.moe.gov.my` via
Playwright/Firefox, fills the MOEIS attendance form, and submits.

Plus (commit `4cbc2c9`) roster Excel upload with replace option + template download.

## Current testing status (2026-06-15)

- **Offline data pipeline (absence detection + credential round-trip + tag
  learning): VALIDATED** via `diag_idme_pipeline.py` against the *real*
  25-student roster (pulled read-only from the portal) seeded into a throwaway
  DB. `AbsenceDetector.detect_absences` computes `roster − present = absent`
  correctly (now **tag-first, name-fallback**), emits dicts whose shape
  (`student_name`/`category`/`sebab_id`/`idpelajar`) feeds `form_filler`, and
  `CredentialManager` Fernet round-trips. **Phase-1 caveat RESOLVED:**
  `_normalize_name` is hardened (bin/binti, parentheticals); the diag now asserts
  no-collision on the real roster, bin/binti + appended-token MATCH, and a
  token-reorder calibration-guard deliberately does NOT match. **Phase-3 added:**
  the diag asserts `record_scan` learns a tag, a student is PRESENT-by-tag
  despite a mismatched scan name (name-free), unmatched scans alert, and coverage
  aggregates. All phases green.
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

- **`_normalize_name` weakness — RESOLVED 2026-06-15 (commit `43169e0`).** Now in
  shared `idme/names.py`: bin/binti canonicalization, parenthetical strip,
  `@`-spacing. Deliberately conservative — **no token-set sort** (it would risk a
  false *present*, worse than a false absent); token reordering is intentionally
  left unmatched and resolved by the RFID-tag path instead. `detect_absences`
  iterates the roster directly so collisions can't silently drop a student.
  Validated by `diag_idme_pipeline.py` (no-collision on the real 25-roster).
  *Latent warm-up caveat:* if two roster names DO collide and only one twin has
  scanned, `_is_present`'s name-fallback marks the still-untagged twin present too
  (a false present during the unresolved window). Consistent with the design's
  "flag, don't guess" stance — `_warn_on_collisions` logs it — but detection
  itself doesn't yet hold the absence; distinct RFID tags fix it once learned.
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
