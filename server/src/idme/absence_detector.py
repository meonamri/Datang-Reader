"""
Absence Detector for IDME Module

Compares the full class roster against today's RFID scans to determine
which students are absent. All absences get the default reason:
PONTENG - MALAS KE SEKOLAH (N0040027).
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import date

from .roster_manager import RosterManager
from .scan_tracker import ScanTracker
from .absence_reason_store import AbsenceReasonStore
from .names import normalize_name
from .moeis_codes import (
    DEFAULT_CATEGORY, DEFAULT_SEBAB_ID, DEFAULT_CATEGORY_MALAY,
    DEFAULT_SEBAB_DESCRIPTION, MOEIS_CATEGORIES, SEBAB_DESCRIPTIONS,
)


class AbsenceDetectorError(Exception):
    """Base exception for absence detector errors."""
    pass


class AbsenceDetector:
    """
    Detects absent students by comparing roster against scans.

    Logic: roster(all students) - scanned(present students) = absent students.
    Each absence is assigned a per-student reason collected before the cutoff (via
    the Telegram bot) when one exists, otherwise the default reason (N0040027).
    """

    def __init__(
        self,
        roster_manager: RosterManager,
        scan_tracker: ScanTracker,
        reason_store: Optional[AbsenceReasonStore] = None,
    ):
        """
        Initialize absence detector.

        Args:
            roster_manager: RosterManager for student lists.
            scan_tracker: ScanTracker for today's scans.
            reason_store: AbsenceReasonStore for per-student reasons (optional;
                when None, every absence gets the default reason — the original
                behaviour).
        """
        self.roster = roster_manager
        self.scans = scan_tracker
        self.reason_store = reason_store
        self.logger = logging.getLogger(__name__)

    def detect_absences(
        self,
        class_name: str,
        scan_date: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """
        Determine which students are absent.

        Process:
        1. Get full roster for the class.
        2. Get list of students who scanned today.
        3. Normalize both sets of names for comparison.
        4. Subtract scanned from roster -> absent.
        5. Assign default reason to each absent student.

        Args:
            class_name: Class name (e.g., '5 UKM').
            scan_date: Date in YYYY-MM-DD format (default: today).

        Returns:
            List of absence dicts:
            [
                {
                    'student_name': 'AHMAD BIN ALI',
                    'class_name': '5 UKM',
                    'category': 'N',
                    'category_malay': 'PONTENG',
                    'sebab_id': 'N0040027',
                    'sebab_description': 'MALAS KE SEKOLAH',
                },
                ...
            ]
        """
        if scan_date is None:
            scan_date = date.today().isoformat()

        # Step 1: Get full roster
        roster = self.roster.get_class_roster(class_name)
        if not roster:
            self.logger.warning(f"No students found in roster for class '{class_name}'")
            return []

        # Step 2: Get today's presence keys. Tag-first: a student is present if
        # their learned RFID tag scanned (name-free, exact). Name set is the
        # fallback for students whose tag hasn't been learned yet.
        present_tags = self.scans.get_scanned_tags(class_name, scan_date)
        scanned_names_raw = self.scans.get_scanned_students(class_name, scan_date)
        scanned_normalized = {self._normalize_name(n) for n in scanned_names_raw}

        # Step 3: Surface normalizer COLLISIONS (calibration guard). If two
        # distinct roster students normalize to the same key, fuzzy name matching
        # can no longer tell them apart — a tap for one would mark BOTH present
        # (a false present, worse than a false absent). We do NOT silently merge
        # them; each roster row is evaluated independently below, and the
        # collision is logged loudly so the tag path (Phase 3) can disambiguate.
        self._warn_on_collisions(class_name, roster)

        # Step 4: Find absent students (in roster but not present). Iterate the
        # roster directly — never key a dict on the normalized name, or colliding
        # students would overwrite each other and silently vanish. Keep the full
        # row so we can carry idpelajar through to form_filler (Seam B).
        absent_rows = sorted(
            (s for s in roster
             if not self._is_present(s, present_tags, scanned_normalized)),
            key=lambda s: s['name'],
        )

        self.logger.info(
            f"Class '{class_name}' on {scan_date}: "
            f"roster={len(roster)}, scanned={len(scanned_normalized)}, "
            f"absent={len(absent_rows)}"
        )

        # Step 5: Assign each absentee a reason. A per-student reason collected
        # before the cutoff (via the Telegram bot) overrides the default; everyone
        # else keeps the default (MALAS KE SEKOLAH) — the original behaviour.
        # Match a stored reason by idpelajar first (exact, portal id), then by
        # normalized name. `idpelajar` (when present) also lets form_filler mark by
        # the portal id instead of the name (Seam B).
        reasons = (
            self.reason_store.get_reasons_for(class_name, scan_date)
            if self.reason_store else {}
        )

        absences = []
        for s in absent_rows:
            reason = self._reason_for(s, reasons)
            absences.append({
                'student_name': s['name'],
                'class_name': class_name,
                'idpelajar': s.get('idpelajar'),
                **reason,
            })

        return absences

    def _reason_for(
        self,
        student: Dict[str, Any],
        reasons: Dict[str, Dict[str, str]],
    ) -> Dict[str, str]:
        """
        Resolve the absence reason for one roster student.

        Looks up a stored reason by idpelajar then normalized name; falls back to
        the default reason when none is recorded. Returns the four reason fields
        the form filler / UI expect (category, category_malay, sebab_id,
        sebab_description).
        """
        entry = None
        idpelajar = student.get('idpelajar')
        if idpelajar:
            entry = reasons.get(AbsenceReasonStore.id_key(idpelajar))
        if entry is None:
            entry = reasons.get(
                AbsenceReasonStore.name_key(self._normalize_name(student['name']))
            )

        if entry is None:
            return {
                'category': DEFAULT_CATEGORY,
                'category_malay': DEFAULT_CATEGORY_MALAY,
                'sebab_id': DEFAULT_SEBAB_ID,
                'sebab_description': DEFAULT_SEBAB_DESCRIPTION,
            }

        sebab_id = entry['sebab_id']
        category = entry['category']
        return {
            'category': category,
            'category_malay': MOEIS_CATEGORIES.get(category, DEFAULT_CATEGORY_MALAY),
            'sebab_id': sebab_id,
            'sebab_description': SEBAB_DESCRIPTIONS.get(sebab_id, ''),
        }

    def get_attendance_summary(
        self,
        class_name: str,
        scan_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get a summary of attendance for a class.

        Args:
            class_name: Class name.
            scan_date: Date (default: today).

        Returns:
            {
                'class_name': '5 UKM',
                'date': '2024-01-15',
                'roster_count': 26,
                'scanned_count': 22,
                'absent_count': 4,
                'scanned_students': ['AHMAD...', ...],
                'absent_students': ['SITI...', ...],
            }
        """
        if scan_date is None:
            scan_date = date.today().isoformat()

        roster = self.roster.get_class_roster(class_name)

        present_tags = self.scans.get_scanned_tags(class_name, scan_date)
        scanned_raw = self.scans.get_scanned_students(class_name, scan_date)
        scanned_normalized = {self._normalize_name(n) for n in scanned_raw}

        # Iterate the roster directly (see detect_absences): keying a dict on the
        # normalized name would silently drop collision pairs. Tag-first presence.
        present_names = sorted(
            s['name'] for s in roster
            if self._is_present(s, present_tags, scanned_normalized)
        )
        absent_names = sorted(
            s['name'] for s in roster
            if not self._is_present(s, present_tags, scanned_normalized)
        )

        return {
            'class_name': class_name,
            'date': scan_date,
            'roster_count': len(roster),
            'scanned_count': len(present_names),
            'absent_count': len(absent_names),
            'scanned_students': present_names,
            'absent_students': absent_names,
        }

    def _is_present(
        self,
        student: Dict[str, Any],
        present_tags: set,
        scanned_normalized: set,
    ) -> bool:
        """
        Decide whether a roster student attended today.

        Tag-first (IDENTITY_RESOLUTION_DESIGN.md §5.3): present if their learned
        RFID tag is in today's scanned tags (exact, name-free). Falls back to the
        normalized-name set for students whose tag hasn't been learned yet.
        """
        tag = student.get('integration_tag')
        if tag and tag in present_tags:
            return True
        return self._normalize_name(student['name']) in scanned_normalized

    def _warn_on_collisions(self, class_name: str, roster: List[Dict[str, Any]]) -> List[str]:
        """
        Log a loud warning when two distinct roster students normalize to the
        same key (the calibration failure mode named in the design: a false
        *present* is worse than a false absent).

        Returns the list of colliding normalized keys (for tests / callers).
        """
        seen: Dict[str, List[str]] = {}
        for s in roster:
            seen.setdefault(self._normalize_name(s['name']), []).append(s['name'])

        collisions = {k: v for k, v in seen.items() if len(v) > 1}
        for key, names in collisions.items():
            self.logger.warning(
                f"Name-normalization COLLISION in class '{class_name}': "
                f"{len(names)} students share key '{key}' ({names}). "
                f"A scan for one would mark all present — disambiguate via RFID tag."
            )
        return list(collisions.keys())

    @staticmethod
    def _normalize_name(name: str) -> str:
        """
        Normalize a Malaysian name for cross-system comparison.

        Thin wrapper around :func:`names.normalize_name` (shared with
        roster_manager). See that function for the full canonicalization rules
        and the deliberately-conservative calibration choices.
        """
        return normalize_name(name)
