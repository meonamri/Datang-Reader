"""
IDME Module Configuration

All configuration from environment variables.
Only 3 env vars needed:
  - IDME_ENABLED: Feature toggle (true/false)
  - IDME_CUTOFF_TIME: Daily submission time (HH:MM, 24h format)
  - IDME_ENCRYPTION_KEY: Fernet key for teacher password encryption
"""

import os
import logging

logger = logging.getLogger(__name__)


class IDMEConfig:
    """Configuration for IDME module. All values from environment."""

    # Feature toggle
    ENABLED = os.getenv('IDME_ENABLED', 'false').lower() == 'true'

    # Scheduler
    CUTOFF_TIME = os.getenv('IDME_CUTOFF_TIME', '09:00')

    # Scheduler auto-confirm. When False (default), the scheduled bulk submission
    # saves re-editable DRAFTS (MENUNGGU PENGESAHAN) so a human confirms each
    # morning during the supervised rollout period. Set true ONLY after a
    # supervised period — true auto-confirms LOCKED (TELAH DISAHKAN) records
    # daily and unattended, which is hard to reverse.
    SCHEDULER_CONFIRM = os.getenv('IDME_SCHEDULER_CONFIRM', 'false').lower() == 'true'

    # Encryption key for teacher passwords
    ENCRYPTION_KEY = os.getenv('IDME_ENCRYPTION_KEY', '')

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

            # Validate cutoff time format
            try:
                parts = cls.CUTOFF_TIME.split(':')
                hour, minute = int(parts[0]), int(parts[1])
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    errors.append(f"Invalid IDME_CUTOFF_TIME: {cls.CUTOFF_TIME}")
            except (ValueError, IndexError):
                errors.append(
                    f"Invalid IDME_CUTOFF_TIME format: {cls.CUTOFF_TIME}. "
                    "Use HH:MM (24h format)."
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
            'cutoff_time': cls.CUTOFF_TIME,
            'scheduler_confirm': cls.SCHEDULER_CONFIRM,
            'database_path': cls.DATABASE_PATH,
            'headless': cls.HEADLESS,
            'debug': cls.DEBUG,
            'session_expiry_hours': cls.SESSION_EXPIRY_HOURS,
            'default_category': cls.DEFAULT_CATEGORY,
            'default_sebab_id': cls.DEFAULT_SEBAB_ID,
            'has_encryption_key': bool(cls.ENCRYPTION_KEY),
            'has_roster_path': bool(cls.ROSTER_EXCEL_PATH),
        }
