# CLAUDE.md — Datang Reader

Split-architecture RFID attendance tracking for the Datang API, with an optional
**IDME module** that submits absences to Malaysia's IDME/MOEIS portal.

See `README.md` for the full architecture and API. This file covers the
operational facts that aren't obvious from the code.

## IDME module (`server/src/idme/`)

At a daily cutoff time the module computes `roster − RFID scans = absent
students`, logs into `idme.moe.gov.my` (Playwright/Firefox), fills the MOEIS
attendance form, and submits. This is a **two-session school**: upper forms
(3–6) submit at a morning cutoff and lower forms (1–2) at an afternoon cutoff.
The scheduler runs one timer per session and each fire submits only that
session's forms; a class is routed to a session purely by the **leading form
number in its class string** (`5 UKM` → Form 5 → morning). A class whose form
maps to no session is never submitted — the settings UI flags these (`no
session`) so they don't silently misfire, the same way it flags class-string
misfires. A class whose string has **no leading form number** (e.g. `MENTARI 1`)
can be pinned to a session with `IDME_CLASS_SESSION_OVERRIDE`
(`"MENTARI 1=morning, MENTARI 2=morning"`, matched verbatim); it resolves
through the single `form_of` chokepoint (to that session's lowest form) so every
consumer — cutoff, scan gate, Telegram routing, settings UI — routes it with no
other change. An explicit override wins over any leading number the string also
has. It is **off by default** (`IDME_ENABLED=false`)
and runs inside the same `datang-reader` container — it is not a separate
service. Datang scanning for every student is unchanged; the only added
behaviour is MOEIS submission for *onboarded* classes (those with a configured
teacher). Classes without a teacher are never submitted to MOEIS.

### Operating it

- **Config (env / `.env`):** `IDME_ENABLED`, `IDME_CUTOFF_TIME_MORNING=HH:MM`
  (upper forms 3–6) and `IDME_CUTOFF_TIME_EVENING=HH:MM` (lower forms 1–2) —
  legacy single `IDME_CUTOFF_TIME` is still honoured as the morning fallback;
  `IDME_ENCRYPTION_KEY` (Fernet, generate with `server/gen_fernet_key.py` —
  generate ONCE, never commit; losing it makes stored teacher credentials
  undecryptable), and `IDME_SCHEDULER_CONFIRM`.
- **`IDME_SCHEDULER_CONFIRM` is the safety gate.** Default **false**: the daily
  scheduler saves re-editable **DRAFTS** (MENUNGGU PENGESAHAN) so a human
  confirms each morning. Set **true** only after a supervised period — true
  **auto-confirms LOCKED records** (TELAH DISAHKAN) daily and unattended, which
  is hard to reverse. Manual `/idme/submit` defaults to a draft; pass
  `{"confirm": true}` to confirm.
- **A full-attendance class is still submitted.** Zero absences is not a
  no-op: an unsubmitted day reads on MOEIS as "attendance never taken", not
  "everyone present", so `_submit_class_async` logs in and submits the untouched
  form (every student is default-checked hadir) with an empty absence list.
  Guarded by the roster: `roster_count == 0` means "we know nothing about this
  class" (roster never initialised, or everyone retired by a portal read), never
  "all present" — that returns `failed` (non-retryable) without a login, and
  deliberately **not** `skipped`, which `submit_all_classes` reads as the
  school-wide non-school-day signal and would abandon every remaining class.
  Tests: `server/test_idme_full_attendance.py`.
- **A class is identified by a string that must match in three places** or it
  silently misfires: the roster `Class`, the Datang scan `section`, and the
  teacher `class_name`. A student name mismatch = that student marked absent
  every day until an RFID tag is learned for them.
- Identity resolution: name bridges roster-init + first scan + card
  replacement; the **RFID tag is the daily key once learned** (tag-first,
  name-fallback). IC is unavailable on both sides. See
  `server/src/idme/IDENTITY_RESOLUTION_DESIGN.md`.
- **Dropped students (transfer/withdrawal) are retired by "Read portal".**
  `RosterManager.upsert_from_portal` sets `enabled = 0` on any registry student
  the portal no longer lists — a **soft** delete, so the row and its learned tag
  survive and a student the portal lists again is re-enabled by the next read
  (matched by `idpelajar` even while disabled). This is load-bearing, not
  cosmetic: a dropped student left enabled is submitted absent daily and has no
  portal checkbox to mark, and a single such `Student checkbox not found` fails
  the **whole class** (`failed_count > 0` ⇒ `status='failed'` in
  `orchestrator._submit_class_async`) every day until someone re-reads the
  portal. An **empty** portal list retires nobody — a bad read is never
  authority to wipe a class. Tests: `server/test_idme_roster_retire.py`.

### Telegram reason collection (optional, off by default)

By default every absence is submitted as `N0040027` PONTENG · MALAS KE SEKOLAH.
An optional Telegram bot lets each class teacher record a **per-student reason**
*before* the cutoff: at a per-session prompt time the bot DMs the teacher their
current absentee list with inline buttons (curated quick-pick + "More…" → full
MOEIS list by category); the chosen reason is stored in the `absence_reasons`
table and `AbsenceDetector.detect_absences` merges it over the default. A student
left untouched keeps MALAS KE SEKOLAH — the original behaviour, so this only
*adds* data the existing submission pipeline already consumes.

- **Config (env / `.env`):** `IDME_TELEGRAM_ENABLED` (default false),
  `IDME_TELEGRAM_BOT_TOKEN` (from @BotFather), `IDME_TELEGRAM_PASSPHRASE` (shared
  self-link secret, **required** when the bot is enabled), and per-session prompt
  times `IDME_TELEGRAM_PROMPT_TIME_MORNING` (default 10:00) /
  `IDME_TELEGRAM_PROMPT_TIME_EVENING` (default 15:00) — must be *before* that
  session's cutoff. Off and independent of `IDME_SCHEDULER_CONFIRM`; needs
  outbound HTTPS to `api.telegram.org`.

### "Hadir (lupa kad)" present-override + notifications

The reason prompt's per-student keyboard leads with a **✅ Hadir (lupa kad)**
button (before any absence reason): the teacher asserts an absentee is actually
present but forgot their RFID card. Tapping it writes a row to `present_overrides`
(`PresentOverrideStore`); `AbsenceDetector` then **drops** that student from
`detect_absences` (never submitted absent) and **counts them present** in
`get_attendance_summary`, so `roster = present + absent` still holds. A present
override and an absence reason are **mutually exclusive** — setting either clears
the other. The confirmation carries an **undo** button (`u|` action) that clears
the override and restores the reason keyboard.

- **14-day limit / admin alert.** `mark_present` returns the student's distinct
  Hadir days in the trailing `IDME_HADIR_WINDOW_DAYS` (default 14, **rolling**
  look-back — assumption, not fixed cycles). When that exceeds `IDME_HADIR_LIMIT`
  (default 3) the bot DMs `IDME_TELEGRAM_ADMIN_CHAT_ID` (numeric, from
  @userinfobot) with the student name + class. **The override is never blocked** —
  a genuinely-present student must not be marked absent; the limit only triggers a
  notification. An unset admin id or a Telegram hiccup only logs (best-effort).
- **Post-submission teacher DM.** After a class is successfully recorded to IDME,
  the class teacher is DM'd *"Kehadiran Kelas [Class] telah direkodkan ke dalam
  IDME."*. Wired via `IDMEOrchestrator.submission_notifier` (set in
  `api_routes.init_idme_module`, so both the scheduled cutoff and manual
  `/idme/submit` fire it), invoked in the **sync** `submit_class` wrapper *after*
  the async workflow returns — so it can't run on an `OrchestratorError`. Fires
  only when something actually reached the portal (`status=='completed'` and the
  form was submitted or students were already-absent-recorded) — an all-present
  day does submit, so it notifies too; **not** on skips or failures.
  Best-effort/guarded — a Telegram failure never breaks a submission.
- **Non-school days (weekends + holidays):** the scheduled prompt is gated by
  **three layers, cheapest first**, all re-evaluated **live at prompt time**
  (`TelegramPromptScheduler._should_prompt`), because the bot — unlike the cutoff
  scheduler — never submits, so it has no `NonSchoolDayError` backstop of its own:
  1. **Weekday guard** (`IDMEConfig.is_school_day`) skips the weekend with no
     data or portal contact. Weekend days come from `IDME_WEEKEND_DAYS` (weekday
     names or 0–6 indices, e.g. `sat,sun`), defaulting to **Fri/Sat** for this
     school.
  2. **Scan gate** (`orchestrator.enough_scans_today` → `ScanTracker.count_scans_on`):
     skips when fewer than `IDME_MIN_SCANS_FOR_SCHOOL_DAY` (default **5**) distinct
     students scanned today. On a real school day students tap in before any
     cutoff, so a near-zero count means a holiday **or a down reader** (in which
     case roster−scans marks the whole school absent — must NOT prompt/submit).
     Cheap DB read, no portal; day-level and school-wide (morning scans ⇒ evening
     is a school day too). **Evaluated live at the moment of action**, never
     frozen — a slow-scan morning or a restart can't wrongly skip or spam.
  3. **Daily portal pre-check** catches public holidays the cheaper gates can't:
     a **single** Playwright login (`orchestrator.check_school_day`, school-wide,
     one login serves both sessions) runs `IDME_TELEGRAM_PRECHECK_LEAD_HOURS`
     (default **1**) before the earliest prompt; its verdict is stored per
     prompt-date and read by both prompts. **A full ~30–60s Firefox login, not
     lightweight** — but the pre-check **skips its own login** when the weekday or
     scan gate already says non-school (storing `None`, never a stale `False`), so
     on holidays it costs nothing. Default lead is **1h** (not 3h) precisely so
     students have already scanned by pre-check time, making the scan gate
     meaningful; a 3h lead would run before students arrive.
  - The **cutoff submission** shares the scan gate: the scheduled fire passes
    `submit_all_classes(..., enforce_scan_gate=True)`, which skips the whole run
    as a non-school day **without any portal login** when scans are below
    threshold (recording skip rows only for in-scope forms). The **manual**
    submit-all path is left ungated (portal `NonSchoolDayError` still backstops a
    deliberate human catch-up).
  - **Failure policy (must stay airtight):** ONLY a *definite* non-school answer
    suppresses — the weekday guard, a below-threshold scan count, or the portal's
    stored `False`. Anything **inconclusive** (portal `None`, a scan-count read
    that errors, or a decision lost to a container restart) falls through to the
    next gate / prompts on a weekday. A flaky portal or DB must never silence a
    real school day. The portal decision is in-memory; a restart loses only that
    day's *portal-holiday* coverage — the weekday and (live) scan gates still hold.
  - **Unverified assumption:** the portal is assumed to report the same
    school-day status at pre-check time as at prompt time (1h later). Confirm
    live against a known holiday before trusting portal holiday coverage; the
    weekend + scan gates do not depend on it. (The probe `check_school_day` has
    unit coverage only for how the scheduler consumes True/False/None — not the
    live portal→verdict mapping. Run it once via `test_idme_login.py` on a real
    holiday.)
  - **Timezone:** all timers use naive container-local `datetime.now()`. Current
    fire times (09:00 pre-check / 10:00 / 15:00) are far from local midnight, so
    the date the guards read is unambiguous whether the container clock is MYT or
    UTC. Keep prompt/pre-check times clear of local midnight if they ever move.
  - On-demand paths (`/kehadiran`, admin "Prompt teacher") are **not** gated —
    explicit human requests work any day.
- **Linking (self-service):** the bot is public (BotFather), so the gate is the
  shared passphrase. A teacher searches the bot, sends `/start`, types
  `IDME_TELEGRAM_PASSPHRASE` (constant-time compared), then taps their class — the
  bot binds their `chat_id` to that class's teacher. Only **unlinked** configured
  classes are offered, so a passphrase-holder can't re-point a colleague's class
  to their own chat; an admin unlinks from `/idme/settings` (read-only Linked /
  Not-linked status + unlink) to free a class for a phone change. A persisted,
  auto-expiring lockout (`telegram_auth_attempts`: 3 tries → ~1h) survives
  restarts so the counter can't be reset by bouncing the container. Teachers are
  routed to a prompt by the same leading-form-number rule as the cutoff scheduler.
  Implementation is `server/src/idme/telegram_bot.py` (requests-based long-polling
  daemon thread — same style as `scheduler.py`, no webhook/asyncio).
- **Re-prompting one class** (a teacher who onboarded *after* the scheduled
  session prompt already fired): the scheduler only fires per session. Two on-
  demand paths cover the straggler — the teacher sends **`/kehadiran`** to pull
  their own current list, or an admin clicks **Prompt teacher** on that class's
  card in `/idme/settings` (`POST /idme/telegram/prompt {class_name}` →
  `bot.prompt_class`). Both **must** run in the live bot instance (the web
  process) — the prompt's button ids live in the bot's in-memory `_entries`, so a
  separate one-off process would send the DM but the teacher's taps would answer
  "session expired". Never start a second poller on the same token (Telegram 409).

### Deploying / turning it on

Rollout is an in-place upgrade of the existing `datang-reader` container.
Follow **`server/IDME_DEPLOY.md`** — it has the volume/bind-mount gotchas and
the post-deploy gating (observe one real scheduled fire; verify per-class
roster/name alignment) that must clear before flipping `IDME_SCHEDULER_CONFIRM`
to true.

## Local test harness (not part of the Docker app)

Windows machine; the IDME test venv is `server/.venv-idme/` (invoke
`.\.venv-idme\Scripts\python.exe` directly). Read-only drivers and offline
diagnostics live in `server/` (`test_idme_login.py`, `diag_idme_*.py`) and are
gitignored along with their PII-bearing dumps. Firefox with HTTP/2 disabled is
**required** for the Malaysian gov portals — do not remove that from
`login_engine._initialize_browser`.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
