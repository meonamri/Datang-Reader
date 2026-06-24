"""
IDME Orchestrator for Datang-Reader

Main workflow coordinator that ties everything together:
  1. Detect absent students (roster - scans)
  2. Get teacher credentials (decrypt password)
  3. Login to IDME portal (6-step Playwright automation)
  4. Fill MOEIS attendance form (uncheck absent students)
  5. Submit to IDME
  6. Log results

This is the single entry point for IDME submissions.
"""

import logging
import asyncio
import time
import sqlite3
from typing import Dict, List, Optional, Any
from datetime import datetime, date
from pathlib import Path

from .idme_config import IDMEConfig
from .credential_manager import CredentialManager, DecryptionError
from .teacher_manager import TeacherManager, TeacherManagerError
from .roster_manager import RosterManager
from .scan_tracker import ScanTracker
from .absence_detector import AbsenceDetector
from .session_cache import SessionCache
from .login_engine import IDMELoginEngine, LoginEngineError, NonSchoolDayError
from .form_filler import IDMEFormFiller, FormFillerError


# Pause before the single run-level retry of a transiently-failed class. Long
# enough to let the gov SSO settle past a momentary bounce, short enough not to
# look like a rapid re-login the portal might rate-limit.
RETRY_DELAY_SECONDS = 5


class OrchestratorError(Exception):
    """Base exception for orchestrator errors."""
    pass


class NoAbsencesError(OrchestratorError):
    """Raised when no absences detected (all students present)."""
    pass


class IDMEOrchestrator:
    """
    Main workflow orchestrator for IDME integration.

    Coordinates all IDME components to detect absences and submit them.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize orchestrator with all components.

        Args:
            db_path: Path to idme_data.db (default: from config).
        """
        self.db_path = db_path or IDMEConfig.DATABASE_PATH
        self.logger = logging.getLogger(__name__)

        # Initialize components
        try:
            self.credential_manager = CredentialManager()
        except Exception as e:
            self.logger.error(f"Failed to init credential manager: {e}")
            raise OrchestratorError(f"Credential manager init failed: {e}")

        self.teacher_manager = TeacherManager(self.db_path, self.credential_manager)
        self.roster_manager = RosterManager(self.db_path)
        self.scan_tracker = ScanTracker(self.db_path)
        self.absence_detector = AbsenceDetector(self.roster_manager, self.scan_tracker)
        self.session_cache = SessionCache(self.db_path)

        self.logger.info("IDME Orchestrator initialized")

    def submit_class(
        self,
        teacher_id: int,
        class_name: str,
        submission_date: Optional[str] = None,
        confirm: bool = True
    ) -> Dict[str, Any]:
        """
        Submit absences for one class to IDME portal.

        Synchronous wrapper around the async workflow.

        Args:
            teacher_id: Teacher database ID.
            class_name: Class name (e.g., '5 UKM').
            submission_date: Date in YYYY-MM-DD (default: today).
            confirm: True (default, production) = confirm the day (TELAH DISAHKAN,
                hard to reverse). False = save a re-editable DRAFT (MENUNGGU
                PENGESAHAN) — the safer first-live-test path.

        Returns:
            {
                'class_name': '5 UKM',
                'date': '2024-01-15',
                'roster_count': 26,
                'scanned_count': 22,
                'absent_count': 4,
                'submitted': 4,
                'failed': 0,
                'form_submitted': True,
                'duration': 45.2,
                'status': 'completed',
            }
        """
        return asyncio.run(
            self._submit_class_async(teacher_id, class_name, submission_date, confirm)
        )

    async def _submit_class_async(
        self,
        teacher_id: int,
        class_name: str,
        submission_date: Optional[str] = None,
        confirm: bool = True
    ) -> Dict[str, Any]:
        """Async implementation of submit_class."""
        if submission_date is None:
            submission_date = date.today().isoformat()

        start = datetime.now()
        submission_id = self._create_submission_record(
            teacher_id, class_name, submission_date
        )

        try:
            # Step 1: Detect absences
            self.logger.info(f"Step 1: Detecting absences for {class_name} on {submission_date}")
            absences = self.absence_detector.detect_absences(class_name, submission_date)
            summary = self.absence_detector.get_attendance_summary(class_name, submission_date)

            roster_count = summary['roster_count']
            scanned_count = summary['scanned_count']
            absent_count = len(absences)

            self._update_submission(submission_id, status='running',
                                   total_roster=roster_count,
                                   total_scanned=scanned_count,
                                   total_absent=absent_count)

            if not absences:
                self.logger.info(f"No absences for {class_name} — all {roster_count} present!")
                duration = (datetime.now() - start).total_seconds()
                self._update_submission(submission_id, status='completed',
                                       successful=0, failed=0,
                                       duration=duration)
                return {
                    'class_name': class_name,
                    'date': submission_date,
                    'roster_count': roster_count,
                    'scanned_count': scanned_count,
                    'absent_count': 0,
                    'submitted': 0,
                    'failed': 0,
                    'form_submitted': False,
                    'duration': duration,
                    'status': 'completed',
                    'message': 'All students present',
                }

            self.logger.info(f"Found {absent_count} absent students")

            # Step 2: Get teacher credentials
            self.logger.info(f"Step 2: Getting credentials for teacher ID={teacher_id}")
            try:
                creds = self.teacher_manager.get_teacher_credentials(teacher_id)
            except (TeacherManagerError, DecryptionError) as e:
                raise OrchestratorError(f"Credential error: {e}")

            # Step 3: Login to IDME
            self.logger.info("Step 3: Logging into IDME portal...")
            engine = IDMELoginEngine(
                ic_number=creds['ic_number'],
                password=creds['password'],
                headless=IDMEConfig.HEADLESS,
                debug=IDMEConfig.DEBUG,
            )

            login_result = None
            try:
                login_result = await engine.login_and_navigate()

                if not login_result.get('success'):
                    raise OrchestratorError("IDME login returned failure")

                page = login_result['page']

                # Store session in cache
                self.session_cache.store_session(
                    teacher_id=teacher_id,
                    cookies=login_result.get('cookies', []),
                    csrf_token=login_result.get('csrf_token'),
                    expires_in_hours=IDMEConfig.SESSION_EXPIRY_HOURS,
                )

                # Step 4: Fill and submit form
                self.logger.info("Step 4: Filling MOEIS attendance form...")
                filler = IDMEFormFiller(page, debug=IDMEConfig.DEBUG)

                fill_result = await filler.mark_absences_and_submit(
                    absent_students=absences,
                    delay_between=IDMEConfig.DELAY_BETWEEN_STUDENTS,
                    confirm=confirm,
                )

                duration = (datetime.now() - start).total_seconds()

                success_count = fill_result.get('success', 0)
                skipped_count = fill_result.get('skipped', 0)
                failed_count = fill_result.get('failed', 0)
                form_submitted = fill_result.get('submitted', False)

                # Already-absent students are recorded absent on the portal (the
                # desired end state), so count them as successful — an
                # all-already-absent run reads N/N, not 0/N. `failed` stays the
                # count of students we genuinely could not mark.
                recorded_count = success_count + skipped_count

                # The class is 'completed' when every absent student is recorded
                # absent on the portal: either we marked them this run (then the
                # submit must have landed) or they were already absent (nothing
                # to submit). It's 'failed' only when a student could not be
                # marked, or we made marks but the submit step broke.
                if failed_count > 0:
                    status = 'failed'
                elif success_count > 0 and not form_submitted:
                    status = 'failed'
                else:
                    status = 'completed'
                error_msg = fill_result.get('error') if status == 'failed' else None

                # A failure is safe to auto-retry only if the submit AJAX was
                # never fired (write_attempted=False) — otherwise the portal may
                # already hold the day and a retry would double-submit. Default a
                # MISSING key to True (assume written) so a future fill path that
                # forgets to report fails safe rather than risking a double-submit.
                retryable = status == 'failed' and not fill_result.get(
                    'write_attempted', True
                )

                self._update_submission(
                    submission_id, status=status,
                    successful=recorded_count, failed=failed_count,
                    duration=duration, error=error_msg
                )

                result = {
                    'class_name': class_name,
                    'date': submission_date,
                    'roster_count': roster_count,
                    'scanned_count': scanned_count,
                    'absent_count': absent_count,
                    'submitted': recorded_count,
                    'skipped': skipped_count,
                    'failed': failed_count,
                    'form_submitted': form_submitted,
                    'confirmed': confirm,
                    'portal_status': fill_result.get('status', ''),
                    'duration': duration,
                    'status': status,
                    'retryable': retryable,
                }

                self.logger.info(
                    f"Submission {'completed' if status == 'completed' else 'FAILED'}: "
                    f"{recorded_count}/{absent_count} recorded absent in {duration:.1f}s"
                )

                return result

            finally:
                # Always close browser
                if engine:
                    await engine.close()

        except NonSchoolDayError as e:
            duration = (datetime.now() - start).total_seconds()
            self.logger.info(f"Non-school day — skipping {class_name}: {e}")
            self._update_submission(submission_id, status='skipped', duration=duration)
            return {
                'class_name': class_name,
                'date': submission_date,
                'roster_count': 0,
                'scanned_count': 0,
                'absent_count': 0,
                'submitted': 0,
                'failed': 0,
                'form_submitted': False,
                'duration': duration,
                'status': 'skipped',
                'message': str(e),
            }
        except OrchestratorError:
            raise
        except Exception as e:
            duration = (datetime.now() - start).total_seconds()
            self.logger.error(f"Submission failed: {e}")
            self._update_submission(
                submission_id, status='failed',
                duration=duration, error=str(e)
            )
            raise OrchestratorError(f"Submission failed: {e}")

    def init_roster_from_portal(
        self,
        teacher_id: int,
        class_name: str
    ) -> Dict[str, Any]:
        """
        Seed/refresh the identity registry for a class from the MOEIS portal
        ("Initialise Roster"). READ-ONLY against the portal — logs in, reads the
        student table, and upserts into the local registry. Never marks/submits.

        Synchronous wrapper around the async workflow.

        Returns:
            The diff dict from RosterManager.upsert_from_portal
            ({'added', 'updated', 'renamed', 'removed', ...}).
        """
        return asyncio.run(
            self._init_roster_from_portal_async(teacher_id, class_name)
        )

    async def _init_roster_from_portal_async(
        self,
        teacher_id: int,
        class_name: str
    ) -> Dict[str, Any]:
        """Async implementation of init_roster_from_portal (read-only)."""
        self.logger.info(
            f"Initialising roster for '{class_name}' (teacher ID={teacher_id})"
        )
        try:
            creds = self.teacher_manager.get_teacher_credentials(teacher_id)
        except (TeacherManagerError, DecryptionError) as e:
            raise OrchestratorError(f"Credential error: {e}")

        engine = IDMELoginEngine(
            ic_number=creds['ic_number'],
            password=creds['password'],
            headless=IDMEConfig.HEADLESS,
            debug=IDMEConfig.DEBUG,
        )
        try:
            login_result = await engine.login_and_navigate()
            if not login_result.get('success'):
                raise OrchestratorError("IDME login returned failure")

            self.session_cache.store_session(
                teacher_id=teacher_id,
                cookies=login_result.get('cookies', []),
                csrf_token=login_result.get('csrf_token'),
                expires_in_hours=IDMEConfig.SESSION_EXPIRY_HOURS,
            )

            filler = IDMEFormFiller(login_result['page'], debug=IDMEConfig.DEBUG)
            portal_students = await filler.get_student_list()
        except OrchestratorError:
            raise
        except Exception as e:
            self.logger.error(f"Roster init failed: {e}")
            raise OrchestratorError(f"Roster init failed: {e}")
        finally:
            await engine.close()

        diff = self.roster_manager.upsert_from_portal(class_name, portal_students)
        diff['status'] = 'completed'
        return diff

    def submit_all_classes(
        self,
        submission_date: Optional[str] = None,
        confirm: Optional[bool] = None,
        forms: Optional[set] = None
    ) -> List[Dict[str, Any]]:
        """
        Submit absences for ALL configured teacher-class pairs.

        Called by the scheduler at each session's cutoff time.

        Args:
            submission_date: Date in YYYY-MM-DD (default: today).
            confirm: True = confirm each class (TELAH DISAHKAN, locked). False =
                save re-editable DRAFTS (MENUNGGU PENGESAHAN). When None (the
                scheduler's call), falls back to IDMEConfig.SCHEDULER_CONFIRM,
                which defaults to False (drafts) for the supervised rollout.
            forms: Optional set of form numbers (e.g. {3, 4, 5, 6}) limiting the
                run to one session. When None, every configured class is
                submitted (the manual "submit all" path). The school runs two
                sessions at different cutoffs, so the scheduler passes only the
                forms due at the cutoff that just fired.

        Returns:
            List of per-class results.
        """
        if submission_date is None:
            submission_date = date.today().isoformat()

        if confirm is None:
            confirm = IDMEConfig.SCHEDULER_CONFIRM

        mode = 'CONFIRM (TELAH DISAHKAN, locked)' if confirm else 'DRAFT (MENUNGGU PENGESAHAN)'
        scope = f"forms {sorted(forms)}" if forms is not None else "all forms"
        self.logger.info(
            f"Starting bulk submission for {submission_date} ({scope}) — mode: {mode}"
        )

        teachers = self.teacher_manager.get_all_teachers()
        if not teachers:
            self.logger.warning("No teachers configured — nothing to submit")
            return []

        results = []
        non_school_day = False
        for teacher in teachers:
            class_name = teacher['class_name']
            teacher_id = teacher['id']

            # Skip classes outside this session's forms. A class whose form can't
            # be parsed (form_of -> None) belongs to no session and is skipped by
            # the scheduler here — the settings UI surfaces these separately so
            # they aren't a silent misfire.
            if forms is not None:
                form = IDMEConfig.form_of(class_name)
                if form not in forms:
                    self.logger.debug(
                        f"Skipping {class_name} (form {form}) — not in this "
                        f"session's forms {sorted(forms)}"
                    )
                    continue

            # A non-school day is school-wide: once one class reports the portal's
            # "Tarikh semasa tidak tersedia" state, every remaining class would
            # too. Skip the rest without a full Playwright/Firefox login + SSO
            # each (the only cause of a 'skipped' status today).
            if non_school_day:
                # Persist a skip row too (not just the first class that hit the
                # banner) so the durable submissions log — and the settings UI's
                # daily-run status sourced from it — reflects the full count, not
                # an under-report of 1.
                self._record_skip(teacher_id, class_name, submission_date,
                                  'Non-school day')
                results.append({
                    'class_name': class_name,
                    'date': submission_date,
                    'status': 'skipped',
                    'message': 'Non-school day',
                })
                continue

            self.logger.info(f"Processing: {teacher['name']} → {class_name}")

            try:
                result = self.submit_class(teacher_id, class_name, submission_date, confirm=confirm)
                results.append(result)
                if result.get('status') == 'skipped':
                    non_school_day = True
                    self.logger.info(
                        "Non-school day detected — skipping remaining classes "
                        "without login"
                    )
            except Exception as e:
                self.logger.error(f"Failed for {class_name}: {e}")
                # An exception here propagated out of the login/navigation phase
                # (or a pre-fill error). The submit AJAX lives inside form_filler,
                # which never raises once it has fired the write — so reaching
                # this handler guarantees nothing was committed: safe to retry.
                results.append({
                    'class_name': class_name,
                    'date': submission_date,
                    'status': 'failed',
                    'error': str(e),
                    'retryable': True,
                })

        # Run-level retry pass: give transient, pre-submission failures (a slow
        # AJAX student-table load, or an SSO bounce to the app picker) exactly one
        # more attempt. Only classes that failed BEFORE firing the submit AJAX are
        # eligible (retryable=True) — never a post-write failure, which could
        # double-submit the day. Skipped entirely on a non-school day: those
        # "failures" are the school-wide holiday short-circuit, and a re-login
        # would only hit the same banner.
        if not non_school_day:
            teacher_id_by_class = {t['class_name']: t['id'] for t in teachers}
            retry_targets = [
                i for i, r in enumerate(results)
                if r.get('status') == 'failed' and r.get('retryable')
            ]
            if retry_targets:
                self.logger.info(
                    f"Retry pass: {len(retry_targets)} class(es) failed before "
                    f"submission — retrying each once"
                )
            for i in retry_targets:
                class_name = results[i]['class_name']
                teacher_id = teacher_id_by_class.get(class_name)
                if teacher_id is None:
                    # Class no longer configured — nothing to retry against.
                    continue
                self.logger.info(f"Retry: re-submitting {class_name}")
                time.sleep(RETRY_DELAY_SECONDS)
                try:
                    retry_result = self.submit_class(
                        teacher_id, class_name, submission_date, confirm=confirm
                    )
                    # Replace in place: the retry wrote its own submission row, so
                    # the durable log and the settings UI's latest-per-class view
                    # already reflect it; keep the in-memory list consistent too.
                    results[i] = retry_result
                    if retry_result.get('status') == 'completed':
                        self.logger.info(f"Retry succeeded for {class_name}")
                    else:
                        self.logger.warning(
                            f"Retry did not complete for {class_name}: "
                            f"{retry_result.get('status')}"
                        )
                except Exception as e:
                    self.logger.error(f"Retry failed for {class_name}: {e}")
                    results[i] = {
                        'class_name': class_name,
                        'date': submission_date,
                        'status': 'failed',
                        'error': str(e),
                        'retryable': False,
                    }

        # Summary
        total = len(results)
        completed = sum(1 for r in results if r.get('status') == 'completed')
        skipped = sum(1 for r in results if r.get('status') == 'skipped')
        failed = total - completed - skipped

        self.logger.info(
            f"Bulk submission done: {completed}/{total} succeeded, "
            f"{skipped} skipped (non-school day), {failed} failed"
        )

        return results

    def _create_submission_record(
        self, teacher_id: int, class_name: str, submission_date: str
    ) -> int:
        """Create an initial submission record in the database."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.execute(
                """INSERT INTO idme_submissions
                   (teacher_id, class_name, submission_date, status, started_at)
                   VALUES (?, ?, ?, 'running', ?)""",
                (teacher_id, class_name, submission_date, datetime.now().isoformat())
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            self.logger.warning(f"Failed to create submission record: {e}")
            return 0
        finally:
            conn.close()

    def _update_submission(
        self, submission_id: int, status: str = None,
        total_roster: int = None, total_scanned: int = None,
        total_absent: int = None, successful: int = None,
        failed: int = None, duration: float = None, error: str = None
    ):
        """Update a submission record."""
        if not submission_id:
            return

        updates = []
        params = []

        if status:
            updates.append("status = ?")
            params.append(status)
        if total_roster is not None:
            updates.append("total_roster = ?")
            params.append(total_roster)
        if total_scanned is not None:
            updates.append("total_scanned = ?")
            params.append(total_scanned)
        if total_absent is not None:
            updates.append("total_absent = ?")
            params.append(total_absent)
        if successful is not None:
            updates.append("successful = ?")
            params.append(successful)
        if failed is not None:
            updates.append("failed = ?")
            params.append(failed)
        if duration is not None:
            updates.append("duration_seconds = ?")
            params.append(duration)
        if error:
            updates.append("error_message = ?")
            params.append(error)
        if status in ('completed', 'failed', 'skipped'):
            updates.append("completed_at = ?")
            params.append(datetime.now().isoformat())

        if not updates:
            return

        params.append(submission_id)

        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                f"UPDATE idme_submissions SET {', '.join(updates)} WHERE id = ?",
                params
            )
            conn.commit()
        except sqlite3.Error as e:
            self.logger.warning(f"Failed to update submission: {e}")
        finally:
            conn.close()

    def _record_skip(
        self, teacher_id: int, class_name: str, submission_date: str, message: str
    ):
        """Write a durable 'skipped' submission row for a class skipped without a
        login (the non-school-day short-circuit). Mirrors the row submit_class
        writes for the one class that actually probed the portal, so the log is
        complete. Errors are swallowed by the helpers — logging must never break a
        submission run."""
        submission_id = self._create_submission_record(
            teacher_id, class_name, submission_date
        )
        self._update_submission(submission_id, status='skipped', error=message)

    def get_submissions_for_date(
        self, submission_date: str
    ) -> List[Dict[str, Any]]:
        """All submission rows for a given day, oldest first. Filters on
        ``submission_date`` (the local date the run was *for*), NOT ``created_at``
        (SQLite CURRENT_TIMESTAMP is UTC and would mis-bucket a near-midnight
        fire). Ordered by id ASC so a caller building a latest-per-class map lets
        later rows overwrite earlier ones."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM idme_submissions WHERE submission_date = ? "
                "ORDER BY id ASC",
                (submission_date,)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_submission_history(
        self,
        class_name: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get submission history."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            if class_name:
                rows = conn.execute(
                    "SELECT * FROM idme_submissions WHERE class_name = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (class_name, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM idme_submissions "
                    "ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
