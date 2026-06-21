# IDME production rollout

Turning on the IDME module = an **in-place upgrade** of the existing
`datang-reader` container. There is no separate service. Datang scanning is
unchanged; the only new behaviour is MOEIS submission for classes that have a
configured teacher.

Production runs on the Raspberry Pi: project dir `~/Datang-Reader/server`,
compose project name `server`, host port `8081` (set via `DATANG_HOST_PORT`).

> **Turn-on is gated.** Deploying with `IDME_ENABLED=true` is safe, but leave
> `IDME_SCHEDULER_CONFIRM=false` (drafts) until the post-deploy checks below
> pass. `IDME_SCHEDULER_CONFIRM=true` auto-confirms LOCKED records unattended.

## 1. Code

Merged to `main` (the module is dormant when `IDME_ENABLED=false`). Pull on the
Pi: `cd ~/Datang-Reader && git pull`.

## 2. Secrets — generate the prod Fernet key (do NOT reuse the test key)

On the Pi (or anywhere with `cryptography`):

```bash
python3 server/gen_fernet_key.py
```

Generate it **once**, store it safely. If it changes, already-stored teacher
credentials can't be decrypted.

## 3. Prod `.env` (`~/Datang-Reader/server/.env`)

Add:

```ini
IDME_ENABLED=true
IDME_ENCRYPTION_KEY=<the key from step 2>
# Two sessions: upper forms (3-6) submit at the morning cutoff, lower forms
# (1-2) at the afternoon cutoff. Each after that session's scan window closes.
IDME_CUTOFF_TIME_MORNING=12:00   # 24h; forms 3, 4, 5, 6
IDME_CUTOFF_TIME_EVENING=16:00   # 24h; forms 1, 2
IDME_SCHEDULER_CONFIRM=false     # KEEP false until post-deploy checks pass
```

**Optional — Telegram per-student reason collection.** Off unless you set these.
Lets teachers record why each student is absent (sick, family, etc.) before the
cutoff; untouched students stay MALAS KE SEKOLAH. Independent of the safety gate.
Needs outbound HTTPS to `api.telegram.org`. After deploy, give teachers the bot
name and the passphrase: each teacher searches the bot, sends `/start`, types the
passphrase, and taps their class to self-link (only unlinked classes are offered;
3 wrong tries locks that chat ~1h). To move a teacher to a new phone, unlink them
from `/idme/settings` first, then they re-link.

```ini
IDME_TELEGRAM_ENABLED=true
IDME_TELEGRAM_BOT_TOKEN=<token from @BotFather>
IDME_TELEGRAM_PASSPHRASE=<shared self-link passphrase>   # required when enabled
IDME_TELEGRAM_PROMPT_TIME_MORNING=10:00   # before the morning cutoff
IDME_TELEGRAM_PROMPT_TIME_EVENING=15:00   # before the afternoon cutoff
```

## 4. Volumes — the two gotchas

The merged compose mounts `../docker-data/idme:/data/idme`. Run the pre-flight
helper, which creates the idme data dir and verifies the sqlite bind sources are
**files**:

```bash
bash server/preflight_idme.sh    # run from ~/Datang-Reader/server
```

- **`docker-data/idme` must exist as a directory** before `up` (the helper
  creates it).
- **`queue.db` and `token` bind sources must stay FILES.** If the host path is
  missing, Docker auto-creates it as a **directory**, and sqlite then fails with
  "unable to open database file". Prod already has them as files; the helper
  asserts it.

## 5. Recreate the container

```bash
cd ~/Datang-Reader/server
docker compose up -d --build        # rebuilds image, recreates the 8081 container
docker compose logs -f datang-reader | grep -i idme
```

Confirm the startup log shows the scheduler mode: **`mode: DRAFT (MENUNGGU
PENGESAHAN)`**. If it says CONFIRM, stop — `IDME_SCHEDULER_CONFIRM` is true.

## 6. Onboard classes

Per class to automate:

1. Add the teacher (IC + portal password) via `/idme/settings`.
2. Initialise the roster from the portal (`/idme/settings` → "Initialise Roster
   from Portal", or `POST /idme/roster/init`).
3. **Verify the class string matches in three places** or the class silently
   misfires: roster `Class` == Datang scan `section` == teacher `class_name`.

Only onboarded classes are submitted; onboard gradually.

## 7. Post-deploy gating — clear BEFORE setting `IDME_SCHEDULER_CONFIRM=true`

Every live submit so far was a manual `/idme/submit`. Before trusting unattended
auto-confirm:

- **(a) Observe one real scheduled fire end-to-end** in draft mode. Check the
  drafts landed as MENUNGGU PENGESAHAN on the portal and look right.
- **(b) Per-class roster/name alignment.** Review `/idme/roster/coverage` for
  each class: unmapped students, `no_match`, and ambiguous counts. A name that
  never matches = a student marked absent every day until their RFID tag is
  learned.
- **(c) Supervised period**: let a human confirm each morning's drafts for a few
  days.

Only then, per class you trust, set `IDME_SCHEDULER_CONFIRM=true` and
`docker compose up -d` to recreate. (Re-check the startup log shows
`mode: CONFIRM`.)

## Notes

- A confirmed day (TELAH DISAHKAN) locks the form; re-submitting is a no-op.
  Resetting a confirmed record is done in the portal.
- The throwaway test deployment (compose project `datangtest`, port 8082) is
  separate. Both prod and test compose dirs are named `server`, so always pass
  `-p datangtest` for test — a bare `up` in the wrong dir recreates the PROD
  container.
