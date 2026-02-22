"""
IDME Form Filler for Datang-Reader

Manipulates the MOEIS attendance form to mark students as absent.
Students are CHECKED (present) by default. Marking absent = UNCHECKING.

Phase 1: All absences use PONTENG / MALAS KE SEKOLAH (N0040027).
The form filler supports arbitrary category/reason for future expansion.

Ported from: idme-attendance-automation/automation/form_filler.py
Key patterns preserved:
  - Select2 dropdown manipulation via jQuery
  - Category set first, wait 800ms, then reason
  - 600ms delay between students
  - Submit flow: Kemaskini → Simpan & Sahkan → OK
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
        sebab_id: str = DEFAULT_SEBAB_ID
    ) -> bool:
        """
        Mark a single student as absent.

        Process:
        1. Find checkbox by data-namapelajar
        2. Uncheck it (mark absent)
        3. Set category dropdown (via jQuery/Select2)
        4. Wait 800ms for reason dropdown to populate
        5. Set reason dropdown

        Args:
            student_name: Student name (must match data-namapelajar).
            category: MOEIS category code (default: 'N').
            sebab_id: MOEIS sebab code (default: 'N0040027').

        Returns:
            True if successful, False otherwise.
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
                async ({ studentName, categoryMalay, sebabDescription }) => {
                    // Helper: wait with timeout
                    const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

                    // Step 1: Find checkbox by name
                    const checkbox = document.querySelector(
                        `input.case-hadir[data-namapelajar="${studentName}"]`
                    );
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

                    const categoryDropdown = row.querySelector('select');
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

                    // Wait for reason dropdown to populate
                    await sleep(800);

                    // Step 7: Find reason dropdown (second select in row)
                    const allDropdowns = row.querySelectorAll('select');
                    const reasonDropdown = allDropdowns[1];
                    if (!reasonDropdown) {
                        return { success: true, warning: 'Reason dropdown not found, category set only' };
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
                        return { success: true, warning: `Reason '${sebabDescription}' not in dropdown` };
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
                }
            )

            if result.get('skipped'):
                self.logger.debug(f"'{student_name}' already absent")
                return False

            if result.get('success'):
                if result.get('warning'):
                    self.logger.warning(f"'{student_name}': {result['warning']}")
                else:
                    self.logger.info(f"Marked absent: {student_name}")
                return True
            else:
                self.logger.error(f"Failed: {student_name}: {result.get('error')}")
                return False

        except Exception as e:
            self.logger.error(f"Exception for '{student_name}': {e}")
            return False

    async def mark_absences_and_submit(
        self,
        absent_students: List[Dict[str, str]],
        delay_between: float = 0.6
    ) -> Dict[str, Any]:
        """
        Mark all absent students and submit the form.

        Args:
            absent_students: List of dicts with 'student_name', 'category', 'sebab_id'.
            delay_between: Delay between students in seconds (default: 0.6).

        Returns:
            {
                'total': 4,
                'success': 4,
                'failed': 0,
                'submitted': True,
                'duration': 12.3,
            }
        """
        start = time.time()
        total = len(absent_students)
        success = 0
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
            }

        await self._take_screenshot("before_marking")

        # Mark each absent student
        self.logger.info(f"Marking {total} students as absent...")
        for i, absence in enumerate(absent_students, 1):
            name = absence['student_name']
            category = absence.get('category', DEFAULT_CATEGORY)
            sebab_id = absence.get('sebab_id', DEFAULT_SEBAB_ID)

            self.logger.info(f"[{i}/{total}] {name}...")
            result = await self.mark_student_absent(name, category, sebab_id)

            if result:
                success += 1
            else:
                failed += 1

            if i < total:
                await asyncio.sleep(delay_between)

        self.logger.info(f"Marking complete: {success}/{total} success, {failed} failed")

        # Submit the form
        submitted = False
        if success > 0:
            submitted = await self._submit_form()
        else:
            self.logger.warning("No students marked, skipping submission")

        duration = time.time() - start
        return {
            'total': total,
            'success': success,
            'failed': failed,
            'submitted': submitted,
            'duration': duration,
        }

    async def _submit_form(self) -> bool:
        """
        Submit the MOEIS attendance form.

        3-step process:
        1. Click 'Kemaskini' button
        2. Click 'Simpan & Sahkan' in confirmation modal
        3. Click 'OK' in success modal

        Returns:
            True if submission confirmed.
        """
        self.logger.info("Submitting to IDME...")

        try:
            # Step 1: Click Kemaskini
            self.logger.info("  Clicking 'Kemaskini'...")
            await self._take_screenshot("submit_01_before_kemaskini")
            await self.page.wait_for_selector(
                'button:has-text("Kemaskini")', timeout=5000
            )
            await self.page.click('button:has-text("Kemaskini")')
            await asyncio.sleep(2)
            await self._take_screenshot("submit_02_after_kemaskini")

            # Step 2: Click Simpan & Sahkan
            self.logger.info("  Clicking 'Simpan & Sahkan'...")
            button = await self.page.wait_for_selector(
                'button:has-text("Simpan & Sahkan")',
                state='visible', timeout=10000
            )
            if not button:
                self.logger.error("'Simpan & Sahkan' not found")
                return False

            await button.click()
            await asyncio.sleep(2)
            await self._take_screenshot("submit_03_after_simpan")

            # Step 3: Click OK in success modal
            self.logger.info("  Clicking 'OK'...")
            try:
                ok_button = await self.page.wait_for_selector(
                    'button:has-text("OK")',
                    state='visible', timeout=5000
                )
                if ok_button:
                    await ok_button.click()
                    await asyncio.sleep(1)
                    await self._take_screenshot("submit_04_after_ok")
            except Exception:
                self.logger.warning("OK button not found (may have auto-closed)")

            # Verify submission
            verification = await self.page.evaluate('''() => {
                const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4, strong'))
                    .map(h => h.textContent.trim());
                return {
                    confirmed: headings.some(h => h.includes('TELAH DISAHKAN')),
                    pending: headings.some(h => h.includes('MENUNGGU PENGESAHAN')),
                };
            }''')

            if verification.get('confirmed'):
                self.logger.info("SUBMISSION CONFIRMED (TELAH DISAHKAN)")
                return True
            elif verification.get('pending'):
                self.logger.warning("Status: MENUNGGU PENGESAHAN (pending)")
                return True  # Still counts as submitted
            else:
                self.logger.warning("Could not verify submission status")
                return True  # Assume success if no error

        except Exception as e:
            self.logger.error(f"Submission failed: {e}")
            await self._take_screenshot("submit_ERROR")
            return False
