"""
Unit tests for the Telegram prompt scheduler's school-day gating.

The scheduled Telegram prompt used to fire every calendar day, including the
Fri/Sat weekend — DMing every teacher a full-class false "absent" list (no RFID
scans exist on a non-school day, so detect_absences returns the whole roster).
Unlike the cutoff scheduler, the bot never contacts the MOEIS portal, so it has
no NonSchoolDayError backstop.

Three gates now decide whether to prompt, cheapest first, ALL evaluated live at
prompt time so a slow-scan morning or a container restart can't wrongly skip or
spam:
  * Weekday guard (IDMEConfig.is_school_day) — skips the Fri/Sat weekend.
  * Scan gate (enough_scans_today) — skips when too few students scanned today
    (holiday, or a down reader that would make the prompt a full-roster false
    "absent"). Cheap DB read, no portal.
  * Portal pre-check (school_day_check) — one Playwright login `lead` hours
    before the earliest prompt catches public holidays; its verdict is stored
    per prompt-date and read by both sessions. The pre-check skips its own login
    when the cheaper gates already say non-school (the cost saving).

Failure policy under test (the property that must be airtight): ONLY a definite
non-school answer suppresses — weekend, below-threshold scans, or portal-stored
False. Anything inconclusive (portal None, a scan read that errors, or a lost
decision) falls through and still prompts on a weekday.

Pure logic — no network, no DB, no real timers. Run directly
(`python test_telegram_prompt_schedule.py`) or under pytest.
"""

import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.idme.idme_config import IDMEConfig, _parse_weekend_days, _read_int  # noqa: E402
from src.idme.scan_tracker import ScanTracker  # noqa: E402
from src.idme.telegram_bot import TelegramPromptScheduler  # noqa: E402

# Fixed dates in July 2026: Wed 15th (school day), Fri 17th & Sat 18th (weekend),
# Sun 19th (school day for a Fri/Sat-weekend school).
WED = date(2026, 7, 15)
FRI = date(2026, 7, 17)
SAT = date(2026, 7, 18)
SUN = date(2026, 7, 19)

SESSIONS = [
    {"name": "morning", "forms": [3, 4, 5, 6], "prompt_time": "10:00"},
    {"name": "evening", "forms": [1, 2], "prompt_time": "15:00"},
]


def _enough(value):
    """A scan-gate callable that returns `value` (True/False) or raises if it's
    an Exception instance."""
    if isinstance(value, Exception):
        return MagicMock(side_effect=value)
    return MagicMock(return_value=value)


class WeekendParsingTests(unittest.TestCase):
    def test_default_is_fri_sat(self):
        self.assertEqual(_parse_weekend_days(None, default={4, 5}), {4, 5})
        self.assertEqual(_parse_weekend_days("", default={4, 5}), {4, 5})

    def test_names_and_numbers(self):
        self.assertEqual(_parse_weekend_days("sat,sun", default={4, 5}), {5, 6})
        self.assertEqual(_parse_weekend_days("5, 6", default={4, 5}), {5, 6})
        self.assertEqual(_parse_weekend_days("Friday Saturday", default={0}), {4, 5})

    def test_bad_tokens_ignored_falls_back(self):
        self.assertEqual(_parse_weekend_days("nope,???", default={4, 5}), {4, 5})
        self.assertEqual(_parse_weekend_days("sat,xyz", default={4, 5}), {5})


class ReadIntTests(unittest.TestCase):
    def test_default_and_overrides(self):
        with patch("src.idme.idme_config.os.getenv", return_value=None):
            self.assertEqual(_read_int("X", 5), 5)
        with patch("src.idme.idme_config.os.getenv", return_value="8"):
            self.assertEqual(_read_int("X", 5), 8)

    def test_bad_and_negative_fall_back(self):
        with patch("src.idme.idme_config.os.getenv", return_value="abc"):
            self.assertEqual(_read_int("X", 5), 5)
        with patch("src.idme.idme_config.os.getenv", return_value="-2"):
            self.assertEqual(_read_int("X", 5), 5)


class IsSchoolDayTests(unittest.TestCase):
    def test_fri_sat_are_not_school_days(self):
        with patch.object(IDMEConfig, "WEEKEND_DAYS", {4, 5}):
            self.assertFalse(IDMEConfig.is_school_day(FRI))
            self.assertFalse(IDMEConfig.is_school_day(SAT))
            self.assertTrue(IDMEConfig.is_school_day(WED))
            self.assertTrue(IDMEConfig.is_school_day(SUN))


class ScanCountLiveTests(unittest.TestCase):
    """ScanTracker.count_scans_on against a real SQLite DB — the one new I/O path
    and the load-bearing 'COUNT(*) = distinct students' claim of the scan gate."""

    def setUp(self):
        self.db = str(Path(tempfile.mkdtemp(prefix="idme_scan_")) / "idme_data.db")
        self.st = ScanTracker(self.db)  # runs schema.sql -> daily_scans exists
        self.today = date.today().isoformat()

    def _insert(self, student, class_name, scan_date):
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT OR IGNORE INTO daily_scans "
            "(student_name, class_name, scan_time, scan_date) VALUES (?, ?, ?, ?)",
            (student, class_name, scan_date + "T08:00:00", scan_date))
        conn.commit()
        conn.close()

    def test_counts_are_day_scoped_and_deduped(self):
        self.assertEqual(self.st.count_scans_on(self.today), 0)  # empty
        self._insert("AISYAH", "5 UKM", self.today)
        self._insert("BALQIS", "5 UKM", self.today)
        self._insert("CHONG", "1 UM", self.today)          # different class, same day
        self._insert("DINA", "5 UKM", "2020-01-01")        # different day
        self.assertEqual(self.st.count_scans_on(self.today), 3)  # school-wide, day-scoped
        self.assertEqual(self.st.count_scans_on(), 3)            # default = today
        self.assertEqual(self.st.count_scans_on("2020-01-01"), 1)
        # A second tap by the same student is deduped by idx_scans_unique, so the
        # count stays distinct-students, not taps.
        self._insert("AISYAH", "5 UKM", self.today)
        self.assertEqual(self.st.count_scans_on(self.today), 3)


class ExecuteGateTests(unittest.TestCase):
    """_execute's three live gates. Every path must still reschedule."""

    def _sched(self, scans=None, check=None):
        bot = MagicMock()
        sched = TelegramPromptScheduler(
            bot, SESSIONS, school_day_check=check, enough_scans_today=scans)
        sched.running = True
        sched._schedule_next = MagicMock()  # don't arm a real timer
        return bot, sched

    def _run(self, sched, today, decision="__unset__"):
        ps = sched.sessions[0]
        if decision != "__unset__":
            sched._decision = {today.isoformat(): decision}
        with patch.object(IDMEConfig, "WEEKEND_DAYS", {4, 5}), \
                patch("src.idme.telegram_bot.date") as mock_date:
            mock_date.today.return_value = today
            sched._execute(ps)
        return ps

    def test_weekend_skips_before_touching_scans(self):
        scans = _enough(True)
        bot, sched = self._sched(scans=scans)
        ps = self._run(sched, SAT)
        bot.prompt_session.assert_not_called()
        scans.assert_not_called()  # weekday guard short-circuits first
        sched._schedule_next.assert_called_once_with(ps)

    def test_weekday_enough_scans_prompts(self):
        bot, sched = self._sched(scans=_enough(True))
        ps = self._run(sched, WED)
        bot.prompt_session.assert_called_once_with(ps.session)
        sched._schedule_next.assert_called_once_with(ps)

    def test_weekday_too_few_scans_skips(self):
        # The core new rule: a weekday with <threshold scans is a non-school day.
        bot, sched = self._sched(scans=_enough(False))
        ps = self._run(sched, WED)
        bot.prompt_session.assert_not_called()
        sched._schedule_next.assert_called_once_with(ps)

    def test_scan_gate_evaluated_live_not_from_stored_decision(self):
        # Even if the stored portal decision is None (e.g. pre-check skipped its
        # login when scans were low), a scan count that RECOVERED by prompt time
        # must prompt — proving the gate is live, not frozen.
        bot, sched = self._sched(scans=_enough(True))
        ps = self._run(sched, WED, decision=None)
        bot.prompt_session.assert_called_once_with(ps.session)

    def test_portal_false_skips_even_with_enough_scans(self):
        # A weekday public holiday where staff happened to tap in: scans pass,
        # but the portal said non-school day, so we skip.
        bot, sched = self._sched(scans=_enough(True))
        ps = self._run(sched, WED, decision=False)
        bot.prompt_session.assert_not_called()
        sched._schedule_next.assert_called_once_with(ps)

    def test_scan_gate_errors_fail_open(self):
        # A DB hiccup must not suppress a real school day.
        bot, sched = self._sched(scans=_enough(RuntimeError("db locked")))
        ps = self._run(sched, WED)
        bot.prompt_session.assert_called_once_with(ps.session)

    def test_no_scan_gate_falls_back_to_weekday_only(self):
        # Backward compatible: no scan callable -> weekday guard is sole cheap gate.
        bot, sched = self._sched(scans=None)
        self._run(sched, WED)
        bot.prompt_session.assert_called_once()
        bot2, sched2 = self._sched(scans=None)
        self._run(sched2, SAT)
        bot2.prompt_session.assert_not_called()


class PrecheckTests(unittest.TestCase):
    """_execute_precheck stores only the PORTAL verdict and always reschedules;
    it skips its own login (storing None, never a stale False) when the cheap
    gates already say non-school."""

    def _sched(self, scans, check):
        bot = MagicMock()
        sched = TelegramPromptScheduler(
            bot, SESSIONS, school_day_check=check, enough_scans_today=scans)
        sched.running = True
        sched._schedule_precheck = MagicMock()  # don't arm a real timer
        return sched

    def test_weekend_skips_portal_login_stores_none(self):
        check = MagicMock()
        sched = self._sched(_enough(True), check)
        with patch.object(IDMEConfig, "WEEKEND_DAYS", {4, 5}):
            sched._execute_precheck(SAT)
        check.assert_not_called()  # no Firefox login on a known weekend
        self.assertEqual(sched._decision, {SAT.isoformat(): None})
        sched._schedule_precheck.assert_called_once()

    def test_low_scans_skips_portal_login_stores_none(self):
        # Must store None (not False) so a scan recovery by prompt time can prompt.
        check = MagicMock()
        sched = self._sched(_enough(False), check)
        with patch.object(IDMEConfig, "WEEKEND_DAYS", {4, 5}):
            sched._execute_precheck(WED)
        check.assert_not_called()
        self.assertEqual(sched._decision, {WED.isoformat(): None})
        sched._schedule_precheck.assert_called_once()

    def test_weekday_with_scans_stores_portal_result(self):
        for portal_answer in (True, False, None):
            check = MagicMock(return_value=portal_answer)
            sched = self._sched(_enough(True), check)
            with patch.object(IDMEConfig, "WEEKEND_DAYS", {4, 5}):
                sched._execute_precheck(WED)
            check.assert_called_once()
            self.assertEqual(sched._decision, {WED.isoformat(): portal_answer})
            sched._schedule_precheck.assert_called_once()

    def test_errored_portal_check_stores_none(self):
        check = MagicMock(side_effect=RuntimeError("portal down"))
        sched = self._sched(_enough(True), check)
        with patch.object(IDMEConfig, "WEEKEND_DAYS", {4, 5}):
            sched._execute_precheck(WED)
        self.assertEqual(sched._decision, {WED.isoformat(): None})
        sched._schedule_precheck.assert_called_once()


class PrecheckSchedulingTests(unittest.TestCase):
    """The pre-check fires `precheck_lead` before the earliest prompt."""

    def test_target_is_lead_hours_before_earliest_prompt(self):
        bot = MagicMock()
        sched = TelegramPromptScheduler(bot, SESSIONS, school_day_check=MagicMock(),
                                        enough_scans_today=MagicMock(),
                                        precheck_lead_hours=1)
        # Earliest prompt is 10:00; 1h before = 09:00. From 06:00, that's today.
        self.assertEqual(sched._next_precheck_target(datetime(2026, 7, 15, 6, 0)),
                         datetime(2026, 7, 15, 9, 0))
        # From 09:30 (past today's 09:00), it rolls to tomorrow 09:00.
        self.assertEqual(sched._next_precheck_target(datetime(2026, 7, 15, 9, 30)),
                         datetime(2026, 7, 16, 9, 0))

    def test_default_lead_is_one_hour(self):
        self.assertEqual(IDMEConfig.TELEGRAM_PRECHECK_LEAD_HOURS, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
