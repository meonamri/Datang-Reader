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

## Reader outbox (client/gui/outbox.py)

Every tap is saved to `~/.datang_outbox.db` on the reader before it is sent.
If the server looked unreachable the kiosk shows **Saved** at once; a sync
thread delivers saved taps oldest first (backoff up to 5 min) with their
original `scanned_at`, `event_id` and `reader_id`. The status bar shows
`N WAITING`; outbox counts are also in `~/.datang_stats.json`.

The server makes `POST /card` idempotent on `event_id` in every mode
(`src/request_log.py`), and advertises `capabilities: ["card_event_id", ...]`
on `/status`. Readers resend after a timeout/5xx **only** to a server that
advertises it. Otherwise the tap is held as `uncertain`, never resent.

**Deploy order: server first, then readers.** Inspect a reader's backlog:
`sqlite3 ~/.datang_outbox.db "select status,count(*) from taps group by 1"`.

Auto-reboot: the GUI runs `sudo reboot` once the server has been unreachable
for **60 s** of wall time with no successful health check in between
(`DATANG_REBOOT_AFTER_UNHEALTHY_S`, default 60; it was 30 polls = 2.5-5 min).
Taps made meanwhile are safe in the outbox, but the kiosk takes no taps while
it restarts. During a long server outage a reader therefore reboots about
every 1.5-2 min (20 s unit start delay + boot + 60 s).

## Card screen (GET /cards)

Linked from the RFID coverage section of `/idme/settings`. It lists unknown
cards, searches by card, name or class, lists roster students without a card,
and shows the audit trail (`card_audit`).
- One active card per student: assigning a new card retires the old one;
  the reader then refuses the old card with `CARD_RETIRED`.
- Moving a card that someone else holds needs confirmation.
- Admin-set roster tags (`tag_source='admin'`) are not overwritten by
  Datang.my name matching.
- Same access as `/idme/settings`: private tailnet only, never a public proxy.

Not built yet (deferred by decision 2026-11-03): teacher Mini App, admin portal.
