# IDME — student identity resolution (DESIGN PROPOSAL)

> **Status: PROPOSED — not yet implemented (2026-06-15).**
> This is a forward-looking design, not a record of existing behavior. For why
> the *current* portal automation looks the way it does, see `DESIGN_NOTES.md`.
> Implementation is phased (see "Phased plan" at the end); each phase is shippable
> on its own.

## 1. The problem

The IDME workflow is fundamentally:

```
roster (who should be in class)  −  scans (who actually tapped)  =  absent  → submit to portal
```

That subtraction only works if we can decide, for each roster student, **"did
this person scan today?"** — i.e. we must link a roster entry to a scan event.
There are two distinct matching points ("seams"):

- **Seam A — absence detection:** roster identities vs. **Datang scan** identities.
  This is where the live bug is (`diag_idme_pipeline.py`, 2026-06-15): present
  students get marked absent when their names don't match exactly.
- **Seam B — form filling:** the absent identities vs. the **MOEIS portal** rows
  that `form_filler` has to find and uncheck.

The hard constraint: **Datang and MOEIS share no common stable identifier.**

| System | Identifiers it exposes to us |
|--------|------------------------------|
| Datang scan response | `name`, `section` (class), `pid` (Datang's id), and the RFID `tag` (= `card_id`) we sent |
| MOEIS portal (`get_student_list`) | `data-namapelajar` (name), `data-idpelajar` (MOEIS id) |

`pid` (Datang) and `idpelajar` (MOEIS) are different namespaces. **IC is NOT
available on the scan side — confirmed:** the Datang success `data` carries
`pid · time · time_text · image · name · section · group · …` and **no IC/MyKad**
(`api_client.py`; `ic: None` there is the *request* field we send, not a response
field). So a tap gives us only **name + section + tag (card_id)**. The **portal doesn't expose
IC either** (confirmed 2026-06-15 via `diag_idme_pipeline.py --probe-portal-attrs`:
the attendance row carries only `data-idpelajar` + `data-namapelajar`; columns are
`Bil / Kehadiran / Nama Murid / Sebab Tidak Hadir`). **IC is therefore unavailable
on both sides — it cannot be a key or a tiebreaker anywhere.** So the **only
bridge between a scan and a portal row is the name** — and
names drift (`BINTI`↔`BT`, `BIN`↔`B.`, titles, `@` aliases, ordering). Matching
on a fragile key, every day, for every student, silently, is the root problem.

This gets worse at the multi-teacher/multi-class scale this system targets: more
students ⇒ more name-format drift **and** real same-name collisions across (and
occasionally within) classes.

## 2. Goals / non-goals

**Goals**
- Make the **daily** absent decision depend on a **stable key (RFID tag)**, not names.
- Survive **card replacement** without manual roster edits (cards are re-issued
  often; the card↔student truth is maintained on the Datang side by design).
- Turn silent false-absences into **loud, fixable alerts.**
- Scale to many teachers/classes; make the school Excel import **optional.**

**Non-goals**
- Changing how Datang resolves a card to a student (that stays Datang's job).
- Fixing borrowed/shared cards (a tap is always attributed to the card *owner* —
  inherent to card attendance; out of scope).
- Any change to the proven RFID→Datang scan submission path.

## 3. Core idea: a persistent identity registry + passively-learned tags

Maintain one **persistent student identity registry** that ties the two worlds
together. It is seeded from the portal and **learns RFID tags automatically from
the existing scan stream** — no separate card-import step.

```
            ┌─────────────────────────────────────────────────────┐
            │  student_identity (persistent registry, per student) │
            │   name · class · idpelajar(MOEIS) · current_tag(RFID) │
            └─────────────────────────────────────────────────────┘
                 ▲ (init: name+class)            ▲ (learn: name+class)
                 │                                │
   ┌─────────────┴───────────┐      ┌────────────┴──────────────────┐
   │ MOEIS portal            │      │ Datang scan stream             │
   │ get_student_list →      │      │ record_scan(card_id, resp) →   │
   │ name + idpelajar/class  │      │ name + section + card_id (tag) │
   └─────────────────────────┘      └────────────────────────────────┘
```

**Why this works:** name matching does not vanish, it gets **relocated** from
"every absent student, every day" to three low-frequency, fail-loud moments:

1. **Init** — reconcile the portal roster into the registry (once per class, re-runnable).
2. **A student's first-ever scan** — attach their `current_tag` to their registry row.
3. **A card replacement** — the next scan with the new `card_id` refreshes `current_tag`.

After a student's tag is known, **daily operation is name-free**:

```
scan(card_id) → registry lookup by tag → mark student present
absent = class registry − present-today
submit → form_filler marks by idpelajar (not name)
```

A scan whose (name, class) matches **no** registry row becomes an
**unmatched-scan alert** instead of a silent miss.

## 4. Data model

Augment the existing `students` table (it already has `integration_tag` +
`get_student_by_tag()`), rather than a parallel table:

```sql
ALTER TABLE students ADD COLUMN idpelajar       TEXT;     -- MOEIS data-idpelajar
ALTER TABLE students ADD COLUMN tag_source      TEXT;     -- 'excel' | 'learned' | NULL
ALTER TABLE students ADD COLUMN tag_updated_at  TIMESTAMP;
ALTER TABLE students ADD COLUMN source          TEXT;     -- 'portal' | 'excel'
-- integration_tag is now the CURRENT (possibly learned) RFID tag.
CREATE INDEX IF NOT EXISTS idx_students_idpelajar ON students(idpelajar);

-- New: scans we could not tie to any registry student (the alert surface).
CREATE TABLE IF NOT EXISTS unmatched_scans (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id      TEXT NOT NULL,
    scan_name    TEXT NOT NULL,      -- name Datang returned
    scan_class   TEXT,              -- section Datang returned
    scan_date    DATE NOT NULL,
    resolved     BOOLEAN DEFAULT 0,  -- set when an admin maps/ignores it
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

`daily_scans` is unchanged — it already records `integration_tag` (= card_id),
`student_name`, `class_name`, `scan_date`, so the tag-learning input is already
there.

## 5. The three reconciliation moments

### 5.1 Init — "Initialise Roster" (per teacher, in the settings UI)
1. Log in as the teacher (reuse `login_engine` + `session_cache`), read
   `get_student_list()` → `[{idpelajar, name}, …]` for that teacher's class.
2. Upsert each into `students`: key on `idpelajar` if present, else normalized
   `(name, class)`. Set `source='portal'`, `class_name` from the teacher's class.
3. `integration_tag` is left **NULL** (learned later). Existing learned tags are
   preserved on re-init.
4. Report a diff (added / removed / renamed) for the admin to eyeball.

This makes the **portal authoritative** for name + class + idpelajar, removing
two of the three legs of the class-name-consistency problem.

### 5.2 Tag learning — passive, on every scan (no flow change)
Extend the existing post-success hook (`service_manager` → `scan_tracker`). After
the (unchanged) `record_scan`:
1. Resolve (normalized `scan_name`, `section`) → a registry student.
2. If found and (`integration_tag` is NULL **or** ≠ this `card_id`):
   set `integration_tag = card_id`, `tag_source='learned'`, `tag_updated_at=now`.
   (≠ handles card replacement; the old tag is simply overwritten.)
3. If **not** found: insert an `unmatched_scans` row (deduped per day) and log a
   warning. Never raise — this hook stays best-effort/non-critical.

### 5.3 Daily absence detection — tag-first, name-fallback
Rewrite `AbsenceDetector.detect_absences(class, date)`:
1. `present_tags` = `daily_scans.integration_tag` for (class, date).
2. A registry student is **present** if their `integration_tag ∈ present_tags`
   (exact, name-free) **OR** (fallback, for students with no learned tag yet)
   their normalized name ∈ today's normalized scan names.
3. `absent = enabled registry students in class − present`.
4. Emit the same dict shape we already validated
   (`student_name`/`category`/`sebab_id`) **plus** `idpelajar` for Seam B.

### 5.4 Tag-mapping coverage — surfaced in the settings UI
Because tags are learned lazily, there's a warm-up period where some students are
still tag-less (matched by name fallback). The settings UI **must report this
progress** so an admin knows how far the registry has "learned in" and when
tag-based detection can be trusted:
- Per class (and a school-wide roll-up at multi-class scale):
  **`mapped / total`** = students with a non-NULL `integration_tag` ÷ enabled
  registry students. Show as a count + bar (e.g. "23 / 25 cards mapped").
- List/link the **still-unmapped** students (by name) so the admin can chase the
  stragglers (kids who haven't scanned, or new cards not yet seen).
- Show the **pending `unmatched_scans`** count (scans that matched no student)
  and **ambiguous-scan** count (duplicate-name first taps) as action items.
- Surface `tag_updated_at` so a recently-changed card is visible.

Backed by a read-only aggregate endpoint (e.g. `GET /idme/roster/coverage`); no
PII beyond names already shown in the roster view.

## 6. Seam B — mark by `idpelajar`, not name
`form_filler.mark_student_absent` currently finds the row by `data-namapelajar`.
Add an id-based path: find the checkbox by `data-idpelajar` when the absence
carries one, fall back to name otherwise. Because the registry's `idpelajar`
comes straight from the same `get_student_list` DOM, this match is exact by
construction — Seam B stops depending on names entirely.

## 7. Name normalization hardening (still needed — at the rare moments)
Names still bridge init + first-scan + card-replacement, so `_normalize_name`
must be hardened (it currently only uppercases + collapses spaces, despite a
docstring claiming otherwise):
- Canonicalize bin/binti family: `BIN`/`B.`/`BINTI`/`BT`/`BTE` → one form.
- Strip trailing/parenthetical extras (titles, `(KETUA)`, role tags).
- Decide a rule for `@` aliases (e.g. compare both sides of the `@`).
- Consider **token-set** comparison (compare the set of name words) so word
  order / a dropped middle token doesn't break a match.
- **Calibration matters:** too loose ⇒ two different students collapse to one
  (a genuinely-absent kid recorded present — worse than a false absence). When a
  fuzzy match is ambiguous, prefer **no match + an unmatched-scan alert** over a
  guess. Use `idpelajar` as the tiebreaker where available.

## 8. Edge cases

| Case | Handling |
|------|----------|
| Student's first scan | Reconciled by name once → tag attached; name-free thereafter. |
| Lost/replaced card | Next scan's new `card_id` overwrites `current_tag` automatically. |
| Never-scanned student | Stays tag-less; correctly absent by elimination (no tag needed). |
| Duplicate names in one class | At init the two are distinct registry rows (keyed on `idpelajar`). But a *scan* for that name carries no IC/`idpelajar`, so the **first** tap (before tags are learned) is genuinely ambiguous → flag as an ambiguous-scan alert, do **not** auto-attach. Distinct RFID tags disambiguate them from then on. |
| Borrowed/shared card | Attributed to card **owner** — inherent, unchanged, documented. |
| Class transfer | New (name, class) key → resolved by re-running portal init. |
| Scan for an unknown/unrostered student | `unmatched_scans` alert, not a silent drop. |

## 9. Code touchpoints
- `schema.sql` — new columns + `unmatched_scans` table (+ a small migration for
  existing DBs).
- `roster_manager.py` — registry upserts keyed on idpelajar/(name,class);
  `import_from_excel` stays but becomes optional.
- New: portal-init routine (orchestrator/teacher-scoped) + `/idme/roster/init`
  route + a settings-UI "Initialise Roster" button.
- New: `GET /idme/roster/coverage` aggregate + a settings-UI **tag-mapping
  progress** panel (mapped/total, unmapped list, unmatched/ambiguous counts).
- `scan_tracker.py` (or the service hook) — tag-learning + unmatched logging.
- `absence_detector.py` — tag-first detection; harden `_normalize_name`.
- `form_filler.py` — mark by `idpelajar` with name fallback.
- `diag_idme_pipeline.py` — extend to assert tag-based detection + the hardened
  normalizer cases.

## 10. Backward compatibility / migration
- Additive columns; existing rows get NULLs and keep working via the name path
  until tags are learned.
- The Excel import path is preserved (some schools may prefer it / need tags
  pre-seeded), but is no longer required: portal init + passive tag learning is
  self-sufficient.
- `IDME_ENABLED=false` still bypasses everything (unchanged).

## 11. Open questions
1. ~~Does the MOEIS portal DOM expose IC?~~ **RESOLVED 2026-06-15: NO.**
   `diag_idme_pipeline.py --probe-portal-attrs` shows the attendance row exposes
   only `data-idpelajar` + `data-namapelajar` (columns `Bil / Kehadiran / Nama
   Murid / Sebab Tidak Hadir`). With Datang IC also absent, **IC is unavailable
   on both sides** — duplicate-name disambiguation rests entirely on the RFID tag
   over time, with the first ambiguous tap flagged for manual resolution.
2. **Serial portal logins at scale.** `submit_all_classes` (and a batch roster
   init) log in per teacher via Firefox sequentially. At dozens of classes this
   is slow/fragile. Prefer **per-teacher** actions + `session_cache` reuse; a
   batch path needs failure isolation and possibly staggering.
3. **Credential/secret surface grows** with more teachers — revisit Fernet key
   handling and the `login_engine.py:421` IC-at-INFO log leak before rollout.

## 12. Phased plan (each phase shippable)
1. **Normalizer hardening** + pipeline-test cases. (The floor; smallest, safest.)
2. **Portal "Initialise Roster"** → registry with `idpelajar`; `form_filler`
   marks by `idpelajar` (Seam B fixed). Excel becomes optional.
3. **Passive tag learning** + **tag-first absence detection** + unmatched-scan
   alerts + **settings-UI tag-mapping coverage panel** (§5.4) (Seam A fixed;
   daily op becomes name-free).
