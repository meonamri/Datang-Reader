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
  - IDME_ENCRYPTION_KEY: Fernet key for teacher password encryption
"""

import os
import re
import logging

logger = logging.getLogger(__name__)

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


def _forms_label(forms):
    """Compact, data-driven label for a session's forms ([3,4,5,6] -> 'F3-6',
    [1,2] -> 'F1-2', [2,4] -> 'F2,4'). Used by the settings UI so labels track
    the actual form lists instead of a hardcoded string."""
    fs = sorted(forms)
    if len(fs) > 1 and fs == list(range(fs[0], fs[-1] + 1)):
        return f"F{fs[0]}-{fs[-1]}"
    return "F" + ",".join(str(f) for f in fs)


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

    @staticmethod
    def form_of(class_name):
        """
        Parse the form number (1-6) from a class string. The form is the leading
        integer of the roster's Class column ('5 UKM' -> 5, '6 ATAS' -> 6,
        '2 UM' -> 2). Returns None when no leading number can be read (e.g.
        'PERALIHAN') — such a class belongs to no session and is flagged, not
        submitted.
        """
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
        }
