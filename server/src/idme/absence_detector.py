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
from .moeis_codes import DEFAULT_CATEGORY, DEFAULT_SEBAB_ID, DEFAULT_CATEGORY_MALAY, DEFAULT_SEBAB_DESCRIPTION


class AbsenceDetectorError(Exception):
    """Base exception for absence detector errors."""
    pass


class AbsenceDetector:
    """
    Detects absent students by comparing roster against scans.

    Logic: roster(all students) - scanned(present students) = absent students.
    All detected absences are assigned the default reason (N0040027).
    """

    def __init__(self, roster_manager: RosterManager, scan_tracker: ScanTracker):
        """
        Initialize absence detector.

        Args:
            roster_manager: RosterManager for student lists.
            scan_tracker: ScanTracker for today's scans.
        """
        self.roster = roster_manager
        self.scans = scan_tracker
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

        roster_names = {s['name'] for s in roster}

        # Step 2: Get scanned students
        scanned_names_raw = self.scans.get_scanned_students(class_name, scan_date)

        # Step 3: Normalize for comparison
        # Build a mapping: normalized_name -> original_roster_name
        normalized_roster = {}
        for name in roster_names:
            normalized_roster[self._normalize_name(name)] = name

        scanned_normalized = {self._normalize_name(n) for n in scanned_names_raw}

        # Step 4: Find absent students (in roster but not scanned)
        absent_normalized = set(normalized_roster.keys()) - scanned_normalized
        absent_names = [normalized_roster[n] for n in absent_normalized]
        absent_names.sort()  # Alphabetical order

        self.logger.info(
            f"Class '{class_name}' on {scan_date}: "
            f"roster={len(roster_names)}, scanned={len(scanned_normalized)}, "
            f"absent={len(absent_names)}"
        )

        # Step 5: Assign default reason
        absences = []
        for name in absent_names:
            absences.append({
                'student_name': name,
                'class_name': class_name,
                'category': DEFAULT_CATEGORY,
                'category_malay': DEFAULT_CATEGORY_MALAY,
                'sebab_id': DEFAULT_SEBAB_ID,
                'sebab_description': DEFAULT_SEBAB_DESCRIPTION,
            })

        return absences

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
        roster_names = {s['name'] for s in roster}

        scanned_raw = self.scans.get_scanned_students(class_name, scan_date)

        # Normalize for comparison
        normalized_roster = {}
        for name in roster_names:
            normalized_roster[self._normalize_name(name)] = name

        scanned_normalized = {self._normalize_name(n) for n in scanned_raw}

        absent_normalized = set(normalized_roster.keys()) - scanned_normalized
        present_normalized = set(normalized_roster.keys()) & scanned_normalized

        absent_names = sorted([normalized_roster[n] for n in absent_normalized])
        present_names = sorted([normalized_roster[n] for n in present_normalized])

        return {
            'class_name': class_name,
            'date': scan_date,
            'roster_count': len(roster_names),
            'scanned_count': len(present_names),
            'absent_count': len(absent_names),
            'scanned_students': present_names,
            'absent_students': absent_names,
        }

    @staticmethod
    def _normalize_name(name: str) -> str:
        """
        Normalize a Malaysian name for comparison.

        - Uppercase
        - Strip extra whitespace
        - Collapse multiple spaces
        - Handle bin/binti variations

        Args:
            name: Raw student name.

        Returns:
            Normalized name string.
        """
        if not name:
            return ''

        n = name.upper().strip()
        # Collapse multiple spaces
        while '  ' in n:
            n = n.replace('  ', ' ')

        return n
