# CLAUDE.md — Datang Reader

Split-architecture RFID attendance tracking for the Datang API, with an optional
**IDME module** that submits absences to Malaysia's IDME/MOEIS portal.

See `README.md` for the full architecture and API. This file covers the
operational facts that aren't obvious from the code.

## IDME module (`server/src/idme/`)

At a daily cutoff time the module computes `roster − RFID scans = absent
students`, logs into `idme.moe.gov.my` (Playwright/Firefox), fills the MOEIS
attendance form, and submits. It is **off by default** (`IDME_ENABLED=false`)
and runs inside the same `datang-reader` container — it is not a separate
service. Datang scanning for every student is unchanged; the only added
behaviour is MOEIS submission for *onboarded* classes (those with a configured
teacher). Classes without a teacher are never submitted to MOEIS.

### Operating it

- **Config (env / `.env`):** `IDME_ENABLED`, `IDME_CUTOFF_TIME=HH:MM`,
  `IDME_ENCRYPTION_KEY` (Fernet, generate with `server/gen_fernet_key.py` —
  generate ONCE, never commit; losing it makes stored teacher credentials
  undecryptable), and `IDME_SCHEDULER_CONFIRM`.
- **`IDME_SCHEDULER_CONFIRM` is the safety gate.** Default **false**: the daily
  scheduler saves re-editable **DRAFTS** (MENUNGGU PENGESAHAN) so a human
  confirms each morning. Set **true** only after a supervised period — true
  **auto-confirms LOCKED records** (TELAH DISAHKAN) daily and unattended, which
  is hard to reverse. Manual `/idme/submit` defaults to a draft; pass
  `{"confirm": true}` to confirm.
- **A class is identified by a string that must match in three places** or it
  silently misfires: the roster `Class`, the Datang scan `section`, and the
  teacher `class_name`. A student name mismatch = that student marked absent
  every day until an RFID tag is learned for them.
- Identity resolution: name bridges roster-init + first scan + card
  replacement; the **RFID tag is the daily key once learned** (tag-first,
  name-fallback). IC is unavailable on both sides. See
  `server/src/idme/IDENTITY_RESOLUTION_DESIGN.md`.

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
