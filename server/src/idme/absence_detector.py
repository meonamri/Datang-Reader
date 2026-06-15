"""
Absence Detector for IDME Module

Compares the full class roster against today's RFID scans to determine
which students are absent. All absences get the default reason:
PONTENG - MALAS KE SEKOLAH (N0040027).
"""

import logging
import re
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

    # bin/binti connector tokens (the "son of" / "daughter of" particle). These
    # drift heavily between systems (BIN/B./BN, BINTI/BT/BTE) so they are
    # canonicalised to one form each. Kept DISTINCT (BIN != BINTI) to avoid
    # collapsing two genuinely different students onto one key.
    _BIN_TOKENS = {'BIN', 'B', 'BN', 'IBN'}
    _BINTI_TOKENS = {'BINTI', 'BT', 'BTE', 'BTI', 'BINTE'}

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

        # Step 2: Get scanned students
        scanned_names_raw = self.scans.get_scanned_students(class_name, scan_date)
        scanned_normalized = {self._normalize_name(n) for n in scanned_names_raw}

        # Step 3: Surface normalizer COLLISIONS (calibration guard). If two
        # distinct roster students normalize to the same key, fuzzy name matching
        # can no longer tell them apart — a tap for one would mark BOTH present
        # (a false present, worse than a false absent). We do NOT silently merge
        # them; each roster row is evaluated independently below, and the
        # collision is logged loudly so the tag path (Phase 3) can disambiguate.
        self._warn_on_collisions(class_name, roster)

        # Step 4: Find absent students (in roster but not scanned). Iterate the
        # roster directly — never key a dict on the normalized name, or colliding
        # students would overwrite each other and silently vanish.
        absent_names = sorted(
            s['name'] for s in roster
            if self._normalize_name(s['name']) not in scanned_normalized
        )

        self.logger.info(
            f"Class '{class_name}' on {scan_date}: "
            f"roster={len(roster)}, scanned={len(scanned_normalized)}, "
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

        scanned_raw = self.scans.get_scanned_students(class_name, scan_date)
        scanned_normalized = {self._normalize_name(n) for n in scanned_raw}

        # Iterate the roster directly (see detect_absences): keying a dict on the
        # normalized name would silently drop collision pairs.
        present_names = sorted(
            s['name'] for s in roster
            if self._normalize_name(s['name']) in scanned_normalized
        )
        absent_names = sorted(
            s['name'] for s in roster
            if self._normalize_name(s['name']) not in scanned_normalized
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

    @classmethod
    def _normalize_name(cls, name: str) -> str:
        """
        Normalize a Malaysian name for cross-system comparison.

        The roster name (from the portal / school Excel) and the Datang scan name
        for the SAME student routinely differ in formatting. This canonicalises
        the common, SAFE-to-merge drifts so they compare equal:

        - Uppercase + strip + collapse internal whitespace.
        - Drop parenthetical / bracketed extras: ``(KETUA)``, ``(KP)``, ``[..]``.
        - Canonicalise the bin/binti connector family (``B.``/``BN`` -> ``BIN``,
          ``BT``/``BTE``/``BTI`` -> ``BINTI``) — but ONLY when the token sits
          *between* other tokens, so a leading/trailing initial like ``B`` is not
          mistaken for "bin".
        - Normalise spacing around ``@`` aliases so ``X@Y`` == ``X @ Y`` (both
          sides of the alias are retained verbatim — we do not guess which side
          the other system used).

        Deliberately CONSERVATIVE: token ORDER is preserved (no token-set sort),
        because sorting risks collapsing two distinct students onto one key — a
        false *present* (worse than a false absent). Reordering / dropped-middle-
        token cases are left to the RFID-tag path, not fuzzy name matching.

        Args:
            name: Raw student name.

        Returns:
            Normalized name string.
        """
        if not name:
            return ''

        n = name.upper().strip()
        # Drop parenthetical / bracketed extras: (KETUA), (KP), [..]
        n = re.sub(r'[\(\[][^\)\]]*[\)\]]', ' ', n)
        # Make '@' a standalone token so spacing variants align.
        n = n.replace('@', ' @ ')
        # Tokenise; treat '.' as a separator so "B." -> "B", "BT." -> "BT".
        raw = n.replace('.', ' ').split()

        tokens = []
        last = len(raw) - 1
        for i, t in enumerate(raw):
            medial = 0 < i < last  # connector particles are never first/last
            if medial and t in cls._BIN_TOKENS:
                tokens.append('BIN')
            elif medial and t in cls._BINTI_TOKENS:
                tokens.append('BINTI')
            else:
                tokens.append(t)

        return ' '.join(tokens)
