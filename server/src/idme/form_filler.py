"""
IDME Form Filler for Datang-Reader

Manipulates the MOEIS attendance form to mark students as absent.
Students are CHECKED (present) by default. Marking absent = UNCHECKING.

Phase 1: All absences use PONTENG / MALAS KE SEKOLAH (N0040027).
The form filler supports arbitrary category/reason for future expansion.

!!! Several choices here are NON-OBVIOUS and load-bearing against the LIVE
    portal (reason select = `select.selectsebab`; submit clicks fire via jQuery
    `.trigger('click')`, NOT `page.click()`; confirm button is `.simpansah`, not
    "Simpan & Sahkan"). Before "simplifying" any of them, READ `DESIGN_NOTES.md`
    in this package and re-test — they break silently otherwise.

Ported from: idme-attendance-automation/automation/form_filler.py
Key patterns preserved:
  - Select2 dropdown manipulation via jQuery
  - Category set first, then poll for the lazily-added reason select
  - 600ms delay between students
  - Submit flow: Kemaskini → (.simpan draft | .simpansah confirm)  [see DESIGN_NOTES.md]
"""

import logging
import asyncio
import time
from typing import Dict, List, Any
from pathlib import Path
from datetime import datetime
from playwright.async_api import Page

from .moeis_codes import (
    MOEIS_CATEGORIES, COMPLETE_MOEIS_SEBAB,
    DEFAULT_CATEGORY, DEFAULT_CATEGORY_MALAY,
    DEFAULT_SEBAB_ID, DEFAULT_SEBAB_DESCRIPTION,
    SEBAB_TO_CATEGORY
)


class FormFillerError(Exception):
    """Base exception for form filler errors."""
    pass


class IDMEFormFiller:
    """
    Handles DOM manipulation for MOEIS attendance forms.

    Students are represented as checkboxes (class="case-hadir").
    Present students are CHECKED. To mark absent: UNCHECK.
    After unchecking, category and reason dropdowns appear.
    """

    def __init__(self, page: Page, debug: bool = False):
        """
        Initialize form filler.

        Args:
            page: Playwright page on the MOEIS attendance form.
            debug: Save screenshots during form filling.
        """
        self.page = page
        self.debug = debug
        self.logger = logging.getLogger(__name__)
        # Becomes True the instant the submit AJAX (the modal action click) is
        # fired — the point past which the portal may have committed the day.
        # Callers use it to decide whether a failed submission is safe to retry:
        # only a failure with write_attempted=False is guaranteed pre-write.
        self.write_attempted = False

    async def _take_screenshot(self, name: str):
        """Take screenshot for debugging."""
        if self.debug:
            try:
                screenshot_dir = Path("/data/idme/screenshots")
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                filepath = screenshot_dir / f"{ts}_{name}.png"
                await self.page.screenshot(path=str(filepath))
                self.logger.info(f"Screenshot: {filepath}")
            except Exception as e:
                self.logger.warning(f"Screenshot failed: {e}")

    async def get_student_list(self) -> List[Dict[str, str]]:
        """
        Get list of students from the MOEIS attendance table.

        Returns:
            [{'id': 'M230620...', 'name': 'AHMAD BIN ALI'}, ...]
        """
        students = await self.page.evaluate("""
            () => {
                const checkboxes = document.querySelectorAll('input.case-hadir[type="checkbox"]');
                const students = [];
                checkboxes.forEach(cb => {
                    const id = cb.getAttribute('data-idpelajar');
                    const name = cb.getAttribute('data-namapelajar');
                    if (id && name) {
                        students.push({ id: id, name: name });
                    }
                });
                return students;
            }
        """)

        if not students:
            raise FormFillerError("No students found in attendance table")

        self.logger.info(f"Found {len(students)} students in MOEIS table")
        return students

    async def mark_student_absent(
        self,
        student_name: str,
        category: str = DEFAULT_CATEGORY,
        sebab_id: str = DEFAULT_SEBAB_ID,
        idpelajar: str = None
    ) -> str:
        """
        Mark a single student as absent.

        Process:
        1. Find checkbox by data-idpelajar (exact, name-free) when an idpelajar is
           given; fall back to data-namapelajar otherwise (Seam B,
           IDENTITY_RESOLUTION_DESIGN.md §6).
        2. Uncheck it (mark absent)
        3. Set category dropdown (via jQuery/Select2)
        4. Wait 800ms for reason dropdown to populate
        5. Set reason dropdown

        Args:
            student_name: Student name (matches data-namapelajar; used for the
                fallback path and for logging).
            category: MOEIS category code (default: 'N').
            sebab_id: MOEIS sebab code (default: 'N0040027').
            idpelajar: MOEIS portal student id (data-idpelajar). When provided,
                the checkbox is located by this exact id rather than by name.

        Returns:
            One of: 'marked' (freshly marked absent this run), 'already_absent'
            (the portal already had the student absent — desired state, not a
            failure), or 'failed' (could not be marked).
        """
        # Determine correct category from sebab_id
        correct_category = SEBAB_TO_CATEGORY.get(sebab_id, category)
        category_malay = MOEIS_CATEGORIES.get(correct_category, DEFAULT_CATEGORY_MALAY)
        sebab_info = COMPLETE_MOEIS_SEBAB.get(sebab_id, {})
        sebab_description = sebab_info.get('keterangan', DEFAULT_SEBAB_DESCRIPTION)

        self.logger.debug(
            f"Marking absent: {student_name} → {category_malay} / {sebab_description}"
        )

        try:
            result = await self.page.evaluate(
                """
                async ({ studentName, categoryMalay, sebabDescription, idpelajar }) => {
                    // Helper: wait with timeout
                    const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

                    // Step 1: Find checkbox. Prefer data-idpelajar (exact, name-
                    // free, Seam B); fall back to data-namapelajar by name.
                    const cssEscape = (s) => (window.CSS && CSS.escape)
                        ? CSS.escape(s) : String(s).replace(/"/g, '\\\\"');
                    let checkbox = null;
                    if (idpelajar) {
                        checkbox = document.querySelector(
                            `input.case-hadir[data-idpelajar="${cssEscape(idpelajar)}"]`
                        );
                    }
                    if (!checkbox) {
                        checkbox = document.querySelector(
                            `input.case-hadir[data-namapelajar="${studentName}"]`
                        );
                    }
                    if (!checkbox) {
                        return { success: false, error: 'Student checkbox not found' };
                    }

                    // Step 2: Already absent?
                    if (!checkbox.checked) {
                        return { success: false, error: 'Already marked absent', skipped: true };
                    }

                    // Step 3: Uncheck (mark absent)
                    checkbox.click();
                    await sleep(500);

                    // Step 4: Find row and category dropdown
                    const row = checkbox.closest('tr');
                    if (!row) {
                        return { success: false, error: 'Student row not found' };
                    }

                    const categoryDropdown =
                        row.querySelector('select.selectkategori') ||
                        row.querySelector('select');
                    if (!categoryDropdown) {
                        return { success: false, error: 'Category dropdown not found' };
                    }

                    // Step 5: Find category value by text match
                    let categoryValue = null;
                    for (const option of categoryDropdown.options) {
                        if (option.text.trim() === categoryMalay) {
                            categoryValue = option.value;
                            break;
                        }
                    }
                    if (!categoryValue) {
                        return { success: false, error: `Category '${categoryMalay}' not in dropdown` };
                    }

                    // Step 6: Set category via jQuery (Select2)
                    if (typeof jQuery !== 'undefined') {
                        jQuery(categoryDropdown).val(categoryValue).trigger('change');
                    } else {
                        categoryDropdown.value = categoryValue;
                        categoryDropdown.dispatchEvent(new Event('change', { bubbles: true }));
                    }

                    // Wait for the reason (sebab) dropdown to be injected/populated.
                    // The portal appends a `select.selectsebab` (name="sebabcuti[]")
                    // to the row only after a category is chosen, so re-query for it
                    // here rather than relying on positional index (the row also
                    // contains a duplicate category select).
                    let reasonDropdown = null;
                    for (let i = 0; i < 10; i++) {
                        await sleep(200);
                        reasonDropdown = row.querySelector('select.selectsebab');
                        if (reasonDropdown && reasonDropdown.options.length > 1) break;
                    }
                    if (!reasonDropdown) {
                        return { success: false, error: 'Reason dropdown (select.selectsebab) not found' };
                    }

                    // Step 8: Find reason value by text match
                    let reasonValue = null;
                    for (const option of reasonDropdown.options) {
                        if (option.text.trim() === sebabDescription) {
                            reasonValue = option.value;
                            break;
                        }
                    }
                    if (!reasonValue) {
                        return { success: false, error: `Reason '${sebabDescription}' not in dropdown` };
                    }

                    // Step 9: Set reason via jQuery (Select2)
                    if (typeof jQuery !== 'undefined') {
                        jQuery(reasonDropdown).val(reasonValue).trigger('change');
                    } else {
                        reasonDropdown.value = reasonValue;
                        reasonDropdown.dispatchEvent(new Event('change', { bubbles: true }));
                    }

                    return { success: true };
                }
                """,
                {
                    'studentName': student_name,
                    'categoryMalay': category_malay,
                    'sebabDescription': sebab_description,
                    'idpelajar': idpelajar,
                }
            )

            if result.get('skipped'):
                # Already unchecked on the portal = already absent. This is the
                # desired end state, not a failure — log at INFO so it's visible
                # (a whole class can be 'already absent' if a teacher filled the
                # day manually) and report it distinctly from a real failure.
                self.logger.info(f"Already absent on portal: {student_name}")
                return 'already_absent'

            if result.get('success'):
                if result.get('warning'):
                    self.logger.warning(f"'{student_name}': {result['warning']}")
                else:
                    self.logger.info(f"Marked absent: {student_name}")
                return 'marked'
            else:
                self.logger.error(f"Failed: {student_name}: {result.get('error')}")
                return 'failed'

        except Exception as e:
            self.logger.error(f"Exception for '{student_name}': {e}")
            return 'failed'

    async def mark_absences_and_submit(
        self,
        absent_students: List[Dict[str, str]],
        delay_between: float = 0.6,
        confirm: bool = True
    ) -> Dict[str, Any]:
        """
        Mark all absent students and submit the form.

        Args:
            absent_students: List of dicts with 'student_name', 'category', 'sebab_id'.
            delay_between: Delay between students in seconds (default: 0.6).
            confirm: If True (default, production), click "Sahkan" (.simpansah) to
                CONFIRM the day (status TELAH DISAHKAN — hard to reverse). If False,
                click "Simpan" (.simpan) to save a re-editable DRAFT (MENUNGGU
                PENGESAHAN).

        Returns:
            {
                'total': 4,
                'success': 4,
                'failed': 0,
                'submitted': True,
                'status': 'TELAH DISAHKAN',
                'duration': 12.3,
            }
        """
        start = time.time()
        total = len(absent_students)
        success = 0
        skipped = 0
        failed = 0

        # Wait for student table to load
        self.logger.info("Waiting for student table...")
        try:
            await self.page.wait_for_selector(
                'input.case-hadir[type="checkbox"]',
                state='attached', timeout=10000
            )
        except Exception as e:
            self.logger.error(f"Student table not loaded: {e}")
            return {
                'total': total, 'success': 0, 'failed': total,
                'submitted': False, 'duration': time.time() - start,
                'error': f"Table not found: {e}",
                'write_attempted': self.write_attempted,
            }

        await self._take_screenshot("before_marking")

        # Mark each absent student
        self.logger.info(f"Marking {total} students as absent...")
        for i, absence in enumerate(absent_students, 1):
            name = absence['student_name']
            category = absence.get('category', DEFAULT_CATEGORY)
            sebab_id = absence.get('sebab_id', DEFAULT_SEBAB_ID)
            idpelajar = absence.get('idpelajar')

            self.logger.info(f"[{i}/{total}] {name}...")
            outcome = await self.mark_student_absent(name, category, sebab_id, idpelajar)

            if outcome == 'marked':
                success += 1
            elif outcome == 'already_absent':
                skipped += 1
            else:
                # Any unexpected return is treated as a real failure (fail-safe).
                failed += 1

            if i < total:
                await asyncio.sleep(delay_between)

        self.logger.info(
            f"Marking complete: {success}/{total} marked, "
            f"{skipped} already absent, {failed} failed"
        )

        # Submit the form. Only fire the submit AJAX when we actually toggled a
        # checkbox this run (success > 0). When every absent student was already
        # absent on the portal (skipped) there is nothing new to write, so we
        # skip the submit and report success below — the desired end state
        # already holds.
        #
        # NOTE (pre-SCHEDULER_CONFIRM follow-up): this no-submit path means a day
        # a teacher saved as a DRAFT but never confirmed is seen as "all already
        # absent" and left unconfirmed. Harmless in DRAFT mode (confirm=False);
        # revisit before enabling daily auto-confirm so such a day isn't silently
        # left as a draft.
        status = ''
        if success > 0:
            status = await self._submit_form(confirm=confirm)
        elif skipped > 0 and failed == 0:
            self.logger.info(
                f"All {skipped} absent student(s) already marked on portal — "
                "nothing new to submit"
            )
        else:
            self.logger.warning("No students marked, skipping submission")

        submitted = bool(status)
        duration = time.time() - start
        return {
            'total': total,
            'status': status,
            'success': success,
            'skipped': skipped,
            'failed': failed,
            'submitted': submitted,
            'duration': duration,
            'write_attempted': self.write_attempted,
        }

    async def _submit_form(self, confirm: bool = True) -> str:
        """
        Submit the MOEIS attendance form.

        Live-portal flow (verified 2026-06-15):
        1. Click 'Kemaskini' (button#kemaskiniKehadiran). Its handler only builds
           a client-side confirmation modal — no server write happens yet.
        2. In that modal, click the action button:
             - confirm=True  -> '.simpansah' ("Sahkan"): CONFIRM (TELAH DISAHKAN)
             - confirm=False -> '.simpan'    ("Simpan"): DRAFT  (MENUNGGU PENGESAHAN)
           This click is what fires the $.ajax POST to kemaskiniKehadiranHarian.
           (The old '.has-text("Simpan & Sahkan")' selector matched only a DISABLED
           button and never actually submitted.)
        3. Dismiss an optional trailing success dialog (SweetAlert), then read the
           resulting day status.

        Args:
            confirm: True = confirm the day (production); False = save a draft.

        Returns:
            The detected status string ('TELAH DISAHKAN' / 'MENUNGGU PENGESAHAN'),
            or '' on failure. Truthy means the submit landed.
        """
        action_selector = '.simpansah' if confirm else '.simpan'
        action_label = 'Sahkan/CONFIRM' if confirm else 'Simpan/DRAFT'
        self.logger.info(f"Submitting to IDME ({action_label})...")

        try:
            # Step 1: open the confirmation modal (client-side only, no write).
            # Fire via jQuery .trigger('click') rather than Playwright .click():
            # the portal shows a `.loadover` overlay that intercepts pointer
            # events and hangs actionability-based clicks. Triggering the bound
            # handler directly is reliable and matches the dropdown handling.
            await self._take_screenshot("submit_01_before_kemaskini")
            # Dismiss any stray/leftover SweetAlert first — an open single-OK
            # dialog can block the Kemaskini handler from rendering its modal.
            await self.page.evaluate("""() => {
                document.querySelectorAll(
                    '.sweet-alert.visible .confirm, .swal-overlay--show-modal .swal-button--confirm')
                    .forEach(b => { try { b.click(); } catch (e) {} });
            }""")
            self.logger.info("  Clicking 'Kemaskini'...")
            opened = await self.page.evaluate("""() => {
                if (window.jQuery && jQuery('#kemaskiniKehadiran').length) {
                    jQuery('#kemaskiniKehadiran').trigger('click'); return true;
                }
                const el = document.querySelector('#kemaskiniKehadiran');
                if (el) { el.click(); return true; }
                return false;
            }""")
            if not opened:
                self.logger.error("'Kemaskini' button not found. Nothing submitted.")
                return ''

            # The Kemaskini handler renders a SweetAlert modal with the action
            # buttons (.batal/.simpan/.simpansah). Poll for the chosen one to be
            # in the DOM (the swal renders a beat after the trigger; allow ~10s
            # since the page may still be settling after a table reload).
            present = False
            for _ in range(40):
                await asyncio.sleep(0.25)
                present = await self.page.evaluate(
                    "(sel) => document.querySelectorAll(sel).length > 0",
                    action_selector)
                if present:
                    break
            await self._take_screenshot("submit_02_after_kemaskini")
            if not present:
                self.logger.error(
                    f"Modal action button '{action_selector}' did not appear "
                    f"(confirm={confirm}). Nothing submitted.")
                await self._take_screenshot("submit_modal_missing")
                return ''

            # Step 2: click the chosen modal action (this triggers the AJAX write).
            # Mark write_attempted BEFORE the click: once fired, the portal may
            # commit even if everything after (status read) fails, so this class
            # must never be auto-retried past this line.
            self.logger.info(f"  Clicking modal action '{action_selector}'...")
            self.write_attempted = True
            await self.page.evaluate("""(sel) => {
                if (window.jQuery) { jQuery(sel).trigger('click'); }
                else { document.querySelector(sel).click(); }
            }""", action_selector)
            await self._take_screenshot("submit_03_after_action")

            # Step 3: dismiss an optional trailing success/confirm dialog.
            for sel in ('.swal-button--confirm', 'button.confirm',
                        'button:has-text("OK")', 'button:has-text("Ya")'):
                try:
                    el = self.page.locator(sel).first
                    if await el.count() and await el.is_visible():
                        await el.click(timeout=2000)
                        break
                except Exception:
                    pass

            # Step 4: wait for the page to reflect the EXPECTED new status, not
            # just any status. The portal updates the badge asynchronously after
            # the AJAX; reading once can return the *previous* status (e.g. a
            # just-confirmed day still showing MENUNGGU for a beat). Wait for the
            # specific target string so the confirm path isn't misreported.
            expected = 'TELAH DISAHKAN' if confirm else 'MENUNGGU PENGESAHAN'
            try:
                await self.page.wait_for_function(
                    """(want) => ((document.body && document.body.innerText) || '')
                        .includes(want)""",
                    arg=expected, timeout=15000)
            except Exception:
                self.logger.warning(
                    f"Expected status '{expected}' did not appear within timeout")
            await self._take_screenshot("submit_04_after_status")

            status = await self.page.evaluate('''() => {
                const els = Array.from(document.querySelectorAll(
                    'h1,h2,h3,h4,strong,.swal-title,.swal-text,td,.badge'))
                    .map(h => (h.textContent || '').trim());
                if (els.some(t => t.includes('TELAH DISAHKAN'))) return 'TELAH DISAHKAN';
                if (els.some(t => t.includes('MENUNGGU PENGESAHAN'))) return 'MENUNGGU PENGESAHAN';
                return '';
            }''')

            if status == expected:
                self.logger.info(f"Submit status: {status}")
            elif status:
                self.logger.warning(
                    f"Submit status '{status}' != expected '{expected}' "
                    f"(confirm={confirm})")
            else:
                self.logger.warning("Submit completed but status not detected")
            return status

        except Exception as e:
            self.logger.error(f"Submission failed: {e}")
            await self._take_screenshot("submit_ERROR")
            return ''
