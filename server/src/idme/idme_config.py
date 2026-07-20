"""
IDME Module Configuration

All configuration from environment variables.
Core env vars:
  - IDME_ENABLED: Feature toggle (true/false)
  - IDME_CUTOFF_TIME_MORNING / IDME_CUTOFF_TIME_EVENING: per-session daily
    submission times (HH:MM, 24h). The school runs two sessions — upper forms
    (3-6) in the morning, lower forms (1-2) in the afternoon — each with its own
    cutoff. IDME_CUTOFF_TIME (legacy, single cutoff) is still honoured as the
    fallback for the morning session.
  - IDME_CLASS_SESSION_OVERRIDE: pin a class with no leading form number
    (e.g. 'MENTARI 1') to a named session — "Class=session" pairs, comma
    separated, e.g. "MENTARI 1=morning, MENTARI 2=morning".
  - IDME_ENCRYPTION_KEY: Fernet key for teacher password encryption
"""

import os
import re
import logging

logger = logging.getLogger(__name__)

# Weekend (non-school) weekdays, as Python weekday() indices (Mon=0 … Sun=6).
# Malaysia's school week is state-dependent: most states rest Sat/Sun, but
# Kelantan, Terengganu, Kedah and Johor rest Fri/Sat. This school is Fri/Sat, so
# that's the default; `IDME_WEEKEND_DAYS` (e.g. "sat,sun") overrides it per
# deployment. Names/numbers both accepted so multi-school configs stay readable.
_WEEKDAY_NAMES = {
    'mon': 0, 'monday': 0, 'tue': 1, 'tuesday': 1, 'wed': 2, 'wednesday': 2,
    'thu': 3, 'thursday': 3, 'fri': 4, 'friday': 4, 'sat': 5, 'saturday': 5,
    'sun': 6, 'sunday': 6,
}


def _parse_weekend_days(raw, default):
    """Parse `IDME_WEEKEND_DAYS` (comma/space-separated weekday names or 0-6
    indices) into a set of weekday() indices. Falls back to ``default`` when
    unset; ignores unrecognised tokens (logged) so a typo can't silently make
    every day a weekend."""
    raw = (raw or '').strip()
    if not raw:
        return set(default)
    days = set()
    for tok in re.split(r'[\s,]+', raw):
        if not tok:
            continue
        key = tok.lower()
        if key in _WEEKDAY_NAMES:
            days.add(_WEEKDAY_NAMES[key])
        elif key.isdigit() and 0 <= int(key) <= 6:
            days.add(int(key))
        else:
            logger.warning("Ignoring unrecognised IDME_WEEKEND_DAYS token: %r", tok)
    return days or set(default)

# Values that explicitly DISABLE a session's cutoff (vs. leaving it unset, which
# falls through to the default). Lets a single-session school turn a session off
# from config — e.g. IDME_CUTOFF_TIME_EVENING=off — without a code change.
_CUTOFF_DISABLE = {'off', 'none', 'disabled', '-'}


def _read_cutoff(env_name, default):
    """Resolve a session cutoff from the environment.

    Empty/unset -> ``default`` (docker-compose passes ${VAR:-} as an empty
    string, which must mean "unset", not "blank value"). A disabling sentinel
    (see ``_CUTOFF_DISABLE``) -> ``None``, which drops the session entirely.
    """
    raw = (os.getenv(env_name) or '').strip()
    if not raw:
        return default
    if raw.lower() in _CUTOFF_DISABLE:
        return None
    return raw


def _read_int(env_name, default):
    """Resolve a non-negative integer env var, falling back to ``default`` when
    unset or malformed (a bad value must not crash module import)."""
    raw = (os.getenv(env_name) or '').strip()
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError:
        logger.warning("Ignoring non-integer %s=%r; using %s", env_name, raw, default)
        return default
    if val < 0:
        logger.warning("Ignoring negative %s=%r; using %s", env_name, raw, default)
        return default
    return val


def _forms_label(forms):
    """Compact, data-driven label for a session's forms ([3,4,5,6] -> 'F3-6',
    [1,2] -> 'F1-2', [2,4] -> 'F2,4'). Used by the settings UI so labels track
    the actual form lists instead of a hardcoded string."""
    fs = sorted(forms)
    if len(fs) > 1 and fs == list(range(fs[0], fs[-1] + 1)):
        return f"F{fs[0]}-{fs[-1]}"
    return "F" + ",".join(str(f) for f in fs)


def _parse_class_session_override(raw):
    """Parse ``IDME_CLASS_SESSION_OVERRIDE`` into {class_name: session_name}.

    Routing is normally by the leading form number of the class string, so a
    class with no leading number (e.g. 'MENTARI 1') maps to no session and is
    never submitted. This override pins such classes to a named session anyway.
    Format is a comma-separated list of ``Class Name=session`` pairs, where
    session is a SESSIONS name ('morning'/'evening'), e.g.
    ``MENTARI 1=morning, MENTARI 2=morning``. The class name is matched
    VERBATIM (it must equal the roster/teacher class string, the same exact-match
    contract as everywhere else); only the session name is lower-cased. Malformed
    pairs are logged and skipped so one typo can't break module import."""
    raw = (raw or '').strip()
    if not raw:
        return {}
    mapping = {}
    for pair in raw.split(','):
        pair = pair.strip()
        if not pair:
            continue
        name, sep, sess = pair.partition('=')
        name, sess = name.strip(), sess.strip().lower()
        if not sep or not name or not sess:
            logger.warning(
                "Ignoring malformed IDME_CLASS_SESSION_OVERRIDE entry: %r", pair)
            continue
        mapping[name] = sess
    return mapping


def _resolve_form_overrides(class_session_override, sessions):
    """Resolve {class_name: session_name} to {class_name: form}, where the form
    is the target session's LOWEST form — a representative that lands the class
    in that session via the single ``form_of`` chokepoint (so every form-keyed
    consumer routes it without further changes). A class pointed at a session
    that isn't scheduled (disabled cutoff) or doesn't exist is dropped (logged)
    so it stays unrouted and UI-flagged, never silently misrouted."""
    by_name = {s['name']: s for s in sessions}
    out = {}
    for name, sess_name in class_session_override.items():
        sess = by_name.get(sess_name)
        if sess is None:
            logger.warning(
                "IDME_CLASS_SESSION_OVERRIDE routes %r to unknown or disabled "
                "session %r; leaving it unrouted", name, sess_name)
            continue
        out[name] = min(sess['forms'])
    return out


class IDMEConfig:
    """Configuration for IDME module. All values from environment."""

    # Feature toggle
    ENABLED = os.getenv('IDME_ENABLED', 'false').lower() == 'true'

    # Scheduler — two sessions, each with its own cutoff.
    #
    # This is a two-session school: upper forms (3-6) attend the morning session
    # and lower forms (1-2) the afternoon session, so each session's absences are
    # submitted at a different cutoff. A class is mapped to a session purely by
    # the leading form number in its class string (e.g. '5 UKM' -> Form 5 ->
    # morning). A class whose form falls in no session is never submitted — the
    # settings UI flags these so they don't silently misfire.
    #
    # IDME_CUTOFF_TIME (the old single-cutoff var) is kept as the morning
    # fallback so existing deployments keep working without a config change.
    # Each session can be disabled from config (cutoff = off/none/-) so a
    # single-session deployment isn't forced to run the other session.
    CUTOFF_TIME = os.getenv('IDME_CUTOFF_TIME') or '12:00'
    CUTOFF_TIME_MORNING = _read_cutoff('IDME_CUTOFF_TIME_MORNING', CUTOFF_TIME)
    CUTOFF_TIME_EVENING = _read_cutoff('IDME_CUTOFF_TIME_EVENING', '16:00')

    # Telegram bot prompt times — when the bot DMs teachers their current
    # absentee list to collect a per-student reason BEFORE the cutoff submits.
    # Per-session (upper forms in the morning, lower forms in the afternoon),
    # defaulting to safely before the default cutoffs. A disabling sentinel
    # (off/none/-) drops the prompt for that session without dropping its cutoff.
    PROMPT_TIME_MORNING = _read_cutoff('IDME_TELEGRAM_PROMPT_TIME_MORNING', '10:00')
    PROMPT_TIME_EVENING = _read_cutoff('IDME_TELEGRAM_PROMPT_TIME_EVENING', '15:00')

    # Lead time for the daily portal school-day pre-check: a single Playwright
    # login this many hours BEFORE the earliest prompt asks the portal whether
    # today is a school day (catching public holidays the weekday check can't).
    # One check per day, school-wide; both sessions' prompts read its result. If
    # the check is unavailable/inconclusive, prompting falls back to the weekday
    # guard (is_school_day). Default 1h: students scan in well before that, so the
    # cheap scan gate below is already meaningful by pre-check time (a 3h lead
    # would run before students arrive). See TelegramPromptScheduler.
    TELEGRAM_PRECHECK_LEAD_HOURS = _read_int('IDME_TELEGRAM_PRECHECK_LEAD_HOURS', 1)

    # Cheap holiday signal: the fewest distinct students who must have scanned on
    # a day for the system to treat it as a school day. Below this, both the
    # Telegram prompt and the cutoff submission treat the day as a non-school day
    # WITHOUT a portal login — on a real school day students tap in before any
    # cutoff, so a near-zero count means a holiday (or a down reader, in which
    # case roster−0=everyone and we must NOT mass-submit). Evaluated live at the
    # moment of action, not frozen ahead of time. Day-level and school-wide: if
    # the morning has scans, the evening session is a school day too.
    MIN_SCANS_FOR_SCHOOL_DAY = _read_int('IDME_MIN_SCANS_FOR_SCHOOL_DAY', 5)

    # Only sessions with a resolved cutoff are scheduled; a disabled one (cutoff
    # None) is dropped here so the scheduler never arms it and the UI never lists
    # it. `forms_label` is precomputed so display labels track the form lists.
    # `prompt_time` (may be None) is the Telegram bot's pre-cutoff prompt time for
    # the session.
    SESSIONS = [
        {**spec, 'forms_label': _forms_label(spec['forms'])}
        for spec in (
            {
                'name': 'morning',
                'label': 'Morning (upper forms)',
                'cutoff': CUTOFF_TIME_MORNING,
                'prompt_time': PROMPT_TIME_MORNING,
                'forms': [3, 4, 5, 6],
            },
            {
                'name': 'evening',
                'label': 'Afternoon (lower forms)',
                'cutoff': CUTOFF_TIME_EVENING,
                'prompt_time': PROMPT_TIME_EVENING,
                'forms': [1, 2],
            },
        )
        if spec['cutoff'] is not None
    ]

    # Explicit class -> session routing for classes whose string has no leading
    # form number (e.g. 'MENTARI 1'), which form_of alone can't place. Parsed to
    # {class_name: session_name}, then resolved to a representative form so the
    # single form_of chokepoint routes them — the cutoff filter, scan gate,
    # Telegram routing and settings UI all follow with no further changes.
    CLASS_SESSION_OVERRIDE = _parse_class_session_override(
        os.getenv('IDME_CLASS_SESSION_OVERRIDE'))
    _CLASS_FORM_OVERRIDE = _resolve_form_overrides(CLASS_SESSION_OVERRIDE, SESSIONS)

    # Weekend (non-school) days as weekday() indices — defaults to Fri/Sat for
    # this school. The Telegram prompt scheduler skips these; without it the bot
    # would DM teachers on the weekend (and, with no scans that day, mark the
    # whole roster absent). Override per deployment with IDME_WEEKEND_DAYS.
    WEEKEND_DAYS = _parse_weekend_days(os.getenv('IDME_WEEKEND_DAYS'), default={4, 5})

    # Scheduler auto-confirm. When False (default), the scheduled bulk submission
    # saves re-editable DRAFTS (MENUNGGU PENGESAHAN) so a human confirms each
    # morning during the supervised rollout period. Set true ONLY after a
    # supervised period — true auto-confirms LOCKED (TELAH DISAHKAN) records
    # daily and unattended, which is hard to reverse.
    SCHEDULER_CONFIRM = os.getenv('IDME_SCHEDULER_CONFIRM', 'false').lower() == 'true'

    # Encryption key for teacher passwords
    ENCRYPTION_KEY = os.getenv('IDME_ENCRYPTION_KEY', '')

    # Telegram bot (per-student absence-reason collection). Off by default and
    # independent of the submission scheduler — when on it only ADDS reason data
    # the existing pipeline consumes (an unset student keeps the default reason).
    TELEGRAM_ENABLED = os.getenv('IDME_TELEGRAM_ENABLED', 'false').lower() == 'true'
    TELEGRAM_BOT_TOKEN = os.getenv('IDME_TELEGRAM_BOT_TOKEN', '').strip()
    # Shared access passphrase teachers type to the bot to self-link their chat.
    # The bot is public (BotFather), so this single secret — not obscurity — is
    # the gate. Required when the bot is enabled, or no one could ever onboard.
    TELEGRAM_PASSPHRASE = os.getenv('IDME_TELEGRAM_PASSPHRASE', '')
    # Admin's Telegram chat/user id (numeric, from @userinfobot). When set, the
    # bot DMs this chat whenever a student is marked "Hadir (lupa kad)" more than
    # HADIR_LIMIT times inside the rolling HADIR_WINDOW_DAYS window, so the admin
    # can follow up. Unset -> the over-limit alert is silently skipped (the Hadir
    # override itself still works); no other feature depends on it.
    TELEGRAM_ADMIN_CHAT_ID = os.getenv('IDME_TELEGRAM_ADMIN_CHAT_ID', '').strip()

    # "Hadir (lupa kad)" present-override policy. A teacher can tap Hadir on an
    # absentee who is actually present but forgot their RFID card: the student is
    # dropped from that day's absent list AND the tap is recorded. Too many such
    # taps is a pattern worth flagging — when a student's distinct Hadir days in
    # the trailing HADIR_WINDOW_DAYS exceed HADIR_LIMIT, the admin is notified.
    # The override is never blocked (a genuinely-present student must not be
    # marked absent); the limit only triggers a notification. The window is a
    # ROLLING look-back, not fixed calendar cycles.
    HADIR_LIMIT = _read_int('IDME_HADIR_LIMIT', 3)
    HADIR_WINDOW_DAYS = _read_int('IDME_HADIR_WINDOW_DAYS', 14)

    # Database path
    DATABASE_PATH = os.getenv('IDME_DATABASE_PATH', '/data/idme/idme_data.db')

    # Automation settings
    HEADLESS = os.getenv('IDME_HEADLESS', 'true').lower() == 'true'
    DEBUG = os.getenv('IDME_DEBUG', 'false').lower() == 'true'
    SESSION_EXPIRY_HOURS = int(os.getenv('IDME_SESSION_EXPIRY_HOURS', '6'))

    # Form filling
    DEFAULT_CATEGORY = 'N'
    DEFAULT_SEBAB_ID = 'N0040027'
    DELAY_BETWEEN_STUDENTS = 0.6  # seconds

    # Roster
    ROSTER_EXCEL_PATH = os.getenv('IDME_ROSTER_EXCEL_PATH', '')

    # IDME URLs
    LOGIN_URL = 'https://idme.moe.gov.my/login'
    HOME_URL = 'https://idme.moe.gov.my/'
    MOEIS_ATTENDANCE_URL = 'https://moeispel.moe.gov.my/sahsiah/kehadiran/tabguru'

    @staticmethod
    def _parse_hhmm(value):
        """Parse an 'HH:MM' (24h) string to minutes-since-midnight, or None if it
        isn't a valid time. Used to validate/compare cutoff and prompt times."""
        try:
            parts = (value or '').split(':')
            hour, minute = int(parts[0]), int(parts[1])
        except (ValueError, IndexError, AttributeError):
            return None
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return hour * 60 + minute

    @classmethod
    def form_of(cls, class_name):
        """
        Parse the form number (1-6) from a class string. The form is the leading
        integer of the roster's Class column ('5 UKM' -> 5, '6 ATAS' -> 6,
        '2 UM' -> 2). Returns None when no leading number can be read (e.g.
        'PERALIHAN') — such a class belongs to no session and is flagged, not
        submitted.

        A class listed in IDME_CLASS_SESSION_OVERRIDE (e.g. 'MENTARI 1') has no
        leading number to parse; it resolves to a representative form of its
        assigned session instead, so this single chokepoint routes it — and
        therefore every form-keyed consumer (cutoff filter, scan gate, Telegram
        routing, settings UI) does too. The explicit override wins over any
        leading number the string might also have.
        """
        override = cls._CLASS_FORM_OVERRIDE.get(class_name)
        if override is not None:
            return override
        m = re.match(r'\s*(\d+)', class_name or '')
        return int(m.group(1)) if m else None

    @classmethod
    def session_for_form(cls, form):
        """Return the session dict a form number belongs to, or None. Takes the
        already-parsed form so a caller that also needs the form doesn't parse
        the class string twice."""
        if form is None:
            return None
        for session in cls.SESSIONS:
            if form in session['forms']:
                return session
        return None

    @classmethod
    def session_of(cls, class_name):
        """
        Return the session dict ({'name','label','cutoff','forms',...}) a class
        belongs to, by its form number, or None if its form maps to no session.
        """
        return cls.session_for_form(cls.form_of(class_name))

    @classmethod
    def is_school_day(cls, d):
        """Whether ``d`` (a date/datetime) is a school day, i.e. not a configured
        weekend day. Note: this is a weekday check only — it does NOT know about
        public holidays. The MOEIS portal backstops the actual submission on
        holidays, but the Telegram prompt has no such check, so on a public
        holiday the bot will still fire."""
        return d.weekday() not in cls.WEEKEND_DAYS

    @classmethod
    def all_session_forms(cls):
        """Union of every scheduled session's forms — the set of forms that are
        eligible for bulk submission. A class whose form is outside this set maps
        to no session and is never submitted by the scheduler or a manual
        submit-all."""
        forms = set()
        for session in cls.SESSIONS:
            forms.update(session['forms'])
        return forms

    @classmethod
    def validate(cls):
        """
        Validate IDME configuration.

        Returns:
            Tuple of (is_valid: bool, errors: list[str])
        """
        errors = []

        if cls.ENABLED:
            if not cls.ENCRYPTION_KEY:
                errors.append(
                    "IDME_ENCRYPTION_KEY is required when IDME is enabled. "
                    "Generate one: python -c \"from cryptography.fernet import Fernet; "
                    "print(Fernet.generate_key().decode())\""
                )

            # At least one session must remain after config-disabling, or the
            # module is enabled but would never submit anything.
            if not cls.SESSIONS:
                errors.append(
                    "No IDME sessions are configured — both cutoffs are disabled. "
                    "Set IDME_CUTOFF_TIME_MORNING and/or IDME_CUTOFF_TIME_EVENING."
                )

            # Validate each session's cutoff time format
            for session in cls.SESSIONS:
                cutoff = session['cutoff']
                cutoff_mins = cls._parse_hhmm(cutoff)
                if cutoff_mins is None:
                    errors.append(
                        f"Invalid {session['name']} cutoff time format: {cutoff}. "
                        "Use HH:MM (24h format)."
                    )

                # The Telegram prompt time, when set, must parse and ideally fire
                # before the cutoff (otherwise reasons can't be collected in time).
                # A late prompt is a warning, not a hard error.
                prompt = session.get('prompt_time')
                if prompt is not None:
                    prompt_mins = cls._parse_hhmm(prompt)
                    if prompt_mins is None:
                        errors.append(
                            f"Invalid {session['name']} prompt time format: {prompt}. "
                            "Use HH:MM (24h format)."
                        )
                    elif cutoff_mins is not None and prompt_mins >= cutoff_mins:
                        logger.warning(
                            f"IDME {session['name']} Telegram prompt time {prompt} is "
                            f"not before its cutoff {cutoff} — reasons may not be "
                            "collected in time."
                        )

            # The bot can't onboard any teacher without the shared passphrase,
            # so an enabled bot with no passphrase is a misconfiguration.
            if cls.TELEGRAM_ENABLED and not cls.TELEGRAM_PASSPHRASE:
                errors.append(
                    "IDME_TELEGRAM_PASSPHRASE is required when IDME_TELEGRAM_ENABLED "
                    "is true — teachers type it to the bot to link their chat."
                )

        is_valid = len(errors) == 0

        if is_valid and cls.ENABLED:
            logger.info("IDME configuration validated successfully")
        elif not is_valid:
            for error in errors:
                logger.error(f"IDME config error: {error}")

        return is_valid, errors

    @classmethod
    def to_dict(cls):
        """Return config as dictionary (safe, no secrets)."""
        return {
            'enabled': cls.ENABLED,
            'cutoff_time': cls.CUTOFF_TIME,  # legacy; prefer `sessions` below
            'sessions': [dict(s) for s in cls.SESSIONS],
            'scheduler_confirm': cls.SCHEDULER_CONFIRM,
            'database_path': cls.DATABASE_PATH,
            'headless': cls.HEADLESS,
            'debug': cls.DEBUG,
            'session_expiry_hours': cls.SESSION_EXPIRY_HOURS,
            'default_category': cls.DEFAULT_CATEGORY,
            'default_sebab_id': cls.DEFAULT_SEBAB_ID,
            'has_encryption_key': bool(cls.ENCRYPTION_KEY),
            'has_roster_path': bool(cls.ROSTER_EXCEL_PATH),
            'telegram_enabled': cls.TELEGRAM_ENABLED,
            'has_telegram_token': bool(cls.TELEGRAM_BOT_TOKEN),
            'has_telegram_passphrase': bool(cls.TELEGRAM_PASSPHRASE),
            'has_telegram_admin': bool(cls.TELEGRAM_ADMIN_CHAT_ID),
            'hadir_limit': cls.HADIR_LIMIT,
            'hadir_window_days': cls.HADIR_WINDOW_DAYS,
        }
