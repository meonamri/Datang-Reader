"""
IDME Scheduler for Datang-Reader

Schedules daily IDME submissions at each session's cutoff time. This is a
two-session school: upper forms (3-6) submit at the morning cutoff and lower
forms (1-2) at the afternoon cutoff, so the scheduler runs one independent timer
per session and each fire submits only that session's forms.

Uses threading.Timer for simplicity (no APScheduler dependency). Runs inside the
existing Flask process as daemon threads.
"""

import logging
import threading
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta


class _Session:
    """One scheduled session: a cutoff time, the forms it covers, its own timer,
    and the bookkeeping for its last run."""

    def __init__(self, name: str, label: str, cutoff: str, forms: List[int]):
        self.name = name
        self.label = label
        self.cutoff = cutoff
        self.forms = forms
        self.hour, self.minute = map(int, cutoff.split(':'))
        self.timer: Optional[threading.Timer] = None
        self.last_run: Optional[datetime] = None
        self.last_result: Optional[dict] = None

    def next_target(self, now: datetime) -> datetime:
        """The next datetime this session fires (today if still upcoming, else
        tomorrow)."""
        target = now.replace(hour=self.hour, minute=self.minute,
                             second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        return target


class IDMEScheduler:
    """
    Schedules daily IDME submissions at each session's cutoff time.

    For every session it calculates the seconds until that session's next cutoff
    and arms a timer. After a session fires it submits only that session's forms,
    then reschedules itself for the next day.
    """

    def __init__(self, orchestrator, sessions: List[Dict[str, Any]]):
        """
        Initialize scheduler.

        Args:
            orchestrator: IDMEOrchestrator instance.
            sessions: List of session dicts ({'name','label','cutoff','forms'}),
                typically IDMEConfig.SESSIONS.
        """
        self.orchestrator = orchestrator
        self.sessions = [
            _Session(s['name'], s.get('label', s['name']), s['cutoff'], s['forms'])
            for s in sessions
        ]
        self.running = False
        self.logger = logging.getLogger(__name__)

    def start(self):
        """Start the scheduler (arms one timer per session)."""
        from .idme_config import IDMEConfig
        self.running = True
        for session in self.sessions:
            self._schedule_next(session)
        mode = 'CONFIRM (TELAH DISAHKAN, locked)' if IDMEConfig.SCHEDULER_CONFIRM else 'DRAFT (MENUNGGU PENGESAHAN)'
        cutoffs = ', '.join(
            f"{s.name} {s.hour:02d}:{s.minute:02d} (forms {s.forms})"
            for s in self.sessions
        )
        self.logger.info(
            f"IDME scheduler started. Daily submissions at — {cutoffs} — mode: {mode}"
        )

    def stop(self):
        """Stop the scheduler (cancels every session timer)."""
        self.running = False
        for session in self.sessions:
            if session.timer:
                session.timer.cancel()
                session.timer = None
        self.logger.info("IDME scheduler stopped")

    def _schedule_next(self, session: _Session):
        """Calculate seconds until a session's next cutoff and schedule it."""
        now = datetime.now()
        target = session.next_target(now)
        seconds_until = (target - now).total_seconds()

        session.timer = threading.Timer(seconds_until, self._execute, args=(session,))
        session.timer.daemon = True  # Dies with main process
        session.timer.start()

        self.logger.info(
            f"Next IDME submission ({session.name}, forms {session.forms}): "
            f"{target.strftime('%Y-%m-%d %H:%M')} ({seconds_until / 3600:.1f}h from now)"
        )

    def _execute(self, session: _Session):
        """Execute one session's submission, then reschedule it for tomorrow."""
        self.logger.info(
            f"Cutoff reached for {session.name} session (forms {session.forms})! "
            "Starting IDME submission..."
        )
        session.last_run = datetime.now()

        try:
            results = self.orchestrator.submit_all_classes(forms=set(session.forms))
            session.last_result = {
                'timestamp': session.last_run.isoformat(),
                'results': results,
                'success': True,
            }
            self.logger.info(
                f"Scheduled {session.name} submission completed: {len(results)} classes"
            )
        except Exception as e:
            self.logger.error(f"Scheduled {session.name} submission failed: {e}")
            session.last_result = {
                'timestamp': session.last_run.isoformat(),
                'error': str(e),
                'success': False,
            }

        # Reschedule this session for tomorrow
        if self.running:
            self._schedule_next(session)

    def get_next_run(self) -> Optional[str]:
        """Return when the *earliest* upcoming session fires (ISO format) — used
        for the single countdown chip in the settings UI."""
        if not self.sessions:
            return None
        now = datetime.now()
        return min(s.next_target(now) for s in self.sessions).isoformat()

    def get_status(self) -> dict:
        """Get scheduler status. `sessions` carries the per-session detail; the
        top-level `next_run` (earliest upcoming fire) drives the single countdown
        chip in the settings UI."""
        now = datetime.now()
        sessions = [
            {
                'name': s.name,
                'label': s.label,
                'cutoff_time': f"{s.hour:02d}:{s.minute:02d}",
                'forms': s.forms,
                'next_run': s.next_target(now).isoformat() if self.running else None,
                'last_run': s.last_run.isoformat() if s.last_run else None,
                'last_result': s.last_result,
            }
            for s in self.sessions
        ]
        return {
            'running': self.running,
            'sessions': sessions,
            'next_run': self.get_next_run() if self.running else None,
        }
