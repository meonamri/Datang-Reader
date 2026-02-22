"""
IDME Scheduler for Datang-Reader

Schedules daily IDME submissions at a configurable cutoff time.
Uses threading.Timer for simplicity (no APScheduler dependency).
Runs inside the existing Flask process as a daemon thread.
"""

import logging
import threading
from typing import Optional
from datetime import datetime, timedelta


class IDMEScheduler:
    """
    Schedules daily IDME submissions at a configurable cutoff time.

    The scheduler calculates seconds until the next cutoff time and
    schedules a timer. After execution, it reschedules for the next day.
    """

    def __init__(self, orchestrator, cutoff_time: str = '09:00'):
        """
        Initialize scheduler.

        Args:
            orchestrator: IDMEOrchestrator instance.
            cutoff_time: Daily submission time in HH:MM (24h format).
        """
        self.orchestrator = orchestrator
        self.cutoff_hour, self.cutoff_minute = map(int, cutoff_time.split(':'))
        self.timer: Optional[threading.Timer] = None
        self.running = False
        self.last_run: Optional[datetime] = None
        self.last_result: Optional[dict] = None
        self.logger = logging.getLogger(__name__)

    def start(self):
        """Start the scheduler."""
        self.running = True
        self._schedule_next()
        self.logger.info(
            f"IDME scheduler started. Daily submission at "
            f"{self.cutoff_hour:02d}:{self.cutoff_minute:02d}"
        )

    def stop(self):
        """Stop the scheduler."""
        self.running = False
        if self.timer:
            self.timer.cancel()
            self.timer = None
        self.logger.info("IDME scheduler stopped")

    def _schedule_next(self):
        """Calculate seconds until next cutoff time and schedule."""
        now = datetime.now()
        target = now.replace(
            hour=self.cutoff_hour,
            minute=self.cutoff_minute,
            second=0,
            microsecond=0
        )

        # If cutoff already passed today, schedule for tomorrow
        if now >= target:
            target += timedelta(days=1)

        seconds_until = (target - now).total_seconds()

        self.timer = threading.Timer(seconds_until, self._execute)
        self.timer.daemon = True  # Dies with main process
        self.timer.start()

        self.logger.info(
            f"Next IDME submission: {target.strftime('%Y-%m-%d %H:%M')} "
            f"({seconds_until / 3600:.1f}h from now)"
        )

    def _execute(self):
        """Execute the daily submission, then reschedule."""
        self.logger.info("Cutoff time reached! Starting IDME submission...")
        self.last_run = datetime.now()

        try:
            results = self.orchestrator.submit_all_classes()
            self.last_result = {
                'timestamp': self.last_run.isoformat(),
                'results': results,
                'success': True,
            }
            self.logger.info(f"Scheduled submission completed: {len(results)} classes")
        except Exception as e:
            self.logger.error(f"Scheduled submission failed: {e}")
            self.last_result = {
                'timestamp': self.last_run.isoformat(),
                'error': str(e),
                'success': False,
            }

        # Reschedule for tomorrow
        if self.running:
            self._schedule_next()

    def get_next_run(self) -> Optional[str]:
        """Return when the next submission will run (ISO format)."""
        now = datetime.now()
        target = now.replace(
            hour=self.cutoff_hour,
            minute=self.cutoff_minute,
            second=0,
            microsecond=0
        )
        if now >= target:
            target += timedelta(days=1)
        return target.isoformat()

    def get_status(self) -> dict:
        """Get scheduler status."""
        return {
            'running': self.running,
            'cutoff_time': f"{self.cutoff_hour:02d}:{self.cutoff_minute:02d}",
            'next_run': self.get_next_run() if self.running else None,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'last_result': self.last_result,
        }
