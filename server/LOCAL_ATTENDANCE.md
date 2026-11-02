# Local attendance authority (replacing Datang.my's card lookup)

Phase 1 of `documents/attendance-portal-plan.md` (homelab workspace): card taps
are resolved and recorded by this server instead of by Datang.my, so a Datang.my
outage (25 Oct 2026: 58 timeouts + 11 × 502 in one morning) can no longer fail
a tap. Code: `src/local_attendance.py`; tests: `test_local_attendance.py`.

## Modes — `ATTENDANCE_MODE` in `.env`

| Mode | Who answers a tap | Datang.my contacted? |
|---|---|---|
| `datang` (default) | Datang.my, exactly as before | yes, in the request path |
| `shadow` | Datang.my; the local answer is logged beside it | yes, in the request path |
| `local` | this server (`card_directory` + roster) | only by the background mirror (`ATTENDANCE_DATANG_MIRROR`, default on) |

Changing the mode needs a container recreate, which **replays the legacy offline
queue** (check `GET /status` → `queue.pending` first). In `local` mode startup
does *not* replay that queue.

## How a card is resolved

1. `students.integration_tag` (MOEIS roster, enabled rows; two students on one
   card → treated as unknown, never guessed).
2. `card_directory` — every card Datang.my has answered for, seeded from
   `daily_scans` history and kept current from Datang.my responses in
   `shadow` mode. This covers classes with no IDME teacher/roster
   (4 UKM, MENTARI 1, 6SS2 on 2026-11-02). Rows with `source='admin'` are never
   overwritten.

Unknown cards are refused on the reader (as Datang.my does) and logged to
`unmatched_scans` with `reason='unknown_card'`.

## Endpoints

- `POST /card` — unchanged contract; now also accepts optional `event_id`
  (idempotent resend), `reader_id`, `scanned_at` (ISO-8601, original tap time;
  >2 min in the future or >7 days old is quarantined, not counted).
- `GET /attendance/status` — mode, today's events by status, mirror backlog.
- `GET /attendance/compare?date=YYYY-MM-DD` — shadow verdict: `agree`,
  `class_mismatch`, `local_unknown`, `datang_rejected`.

## Mirror outcomes (local mode)

`sent` · `rejected` (explicit Datang.my error) · `retry` (never reached Datang.my;
resent next pass) · `uncertain` (read timeout / 5xx / bad body — **never resent
automatically**) · `stale` (not today's tap: Datang.my would stamp the wrong day).

## Rollout

1. Deploy with `ATTENDANCE_MODE=shadow` for at least a week of school days;
   check `/attendance/compare` daily (target: 0 `class_mismatch`, 0 `local_unknown`).
2. Switch to `local` with the mirror on; watch `/attendance/status` mirror counts.
3. Turn the mirror off only once nobody uses the Datang.my dashboard.

Rollback: set `ATTENDANCE_MODE=datang` and recreate. `attendance_events` and
`card_directory` are additive tables and are left in place.

Not in this phase (still per the plan): reader-side outbox (clients send
`event_id`/`scanned_at`), admin UI to add/fix cards, Mini App, admin portal.
