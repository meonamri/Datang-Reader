"""
Roster Manager for IDME Module

Manages the student roster (imported from school Excel export).
Provides lookup by class, RFID tag, and name for absence detection.
"""

import sqlite3
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path


class RosterManagerError(Exception):
    """Base exception for roster manager errors."""
    pass


class RosterManager:
    """
    Manages student roster from Excel import.
    Stores students in idme_data.db for lookup during absence detection.
    """

    def __init__(self, db_path: str):
        """
        Initialize roster manager.

        Args:
            db_path: Path to idme_data.db SQLite database.
        """
        self.db_path = Path(db_path)
        self.logger = logging.getLogger(__name__)
        self._ensure_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_db(self):
        """Ensure the database and students table exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = self._get_conn()
        try:
            schema_path = Path(__file__).parent / 'schema.sql'
            if schema_path.exists():
                conn.executescript(schema_path.read_text())
            conn.commit()
        finally:
            conn.close()

    def import_from_excel(self, excel_path: str) -> Dict[str, int]:
        """
        Import students from school Excel export.

        Expected columns (case-insensitive matching):
        - Name / Nama: Student full name
        - Class / Kelas: Class name (e.g., '5 UKM')
        - IC / No KP / Identification Number: IC number (optional)
        - Integration Tag / Tag: RFID card ID (optional)
        - ID: Student ID (optional)

        Args:
            excel_path: Path to the Excel file.

        Returns:
            {'total': 664, 'imported': 660, 'skipped': 4, 'classes': 28}

        Raises:
            RosterManagerError: If Excel file cannot be read.
        """
        try:
            import openpyxl
        except ImportError:
            raise RosterManagerError(
                "openpyxl is required for Excel import. "
                "Install it: pip install openpyxl"
            )

        excel_file = Path(excel_path)
        if not excel_file.exists():
            raise RosterManagerError(f"Excel file not found: {excel_path}")

        self.logger.info(f"Importing students from: {excel_path}")

        try:
            import pandas as pd
            df = pd.read_excel(excel_path)
        except Exception as e:
            raise RosterManagerError(f"Failed to read Excel file: {e}")

        # Normalize column names (case-insensitive)
        col_map = {}
        for col in df.columns:
            col_lower = col.lower().strip()
            if 'name' in col_lower or 'nama' in col_lower:
                col_map['name'] = col
            elif 'class' in col_lower or 'kelas' in col_lower:
                col_map['class'] = col
            elif 'ic' in col_lower or 'identification' in col_lower or 'kp' in col_lower:
                col_map['ic'] = col
            elif 'integration' in col_lower or 'tag' in col_lower:
                col_map['tag'] = col
            elif col_lower == 'id':
                col_map['id'] = col

        if 'name' not in col_map or 'class' not in col_map:
            raise RosterManagerError(
                f"Excel must have Name and Class columns. "
                f"Found: {list(df.columns)}"
            )

        conn = self._get_conn()
        try:
            imported = 0
            skipped = 0
            classes = set()

            for _, row in df.iterrows():
                name = str(row[col_map['name']]).strip().upper()
                class_name = str(row[col_map['class']]).strip()

                if not name or name == 'NAN' or not class_name or class_name == 'NAN':
                    skipped += 1
                    continue

                # Optional fields
                ic_number = None
                if 'ic' in col_map:
                    ic_val = row[col_map['ic']]
                    if pd.notna(ic_val):
                        ic_number = str(int(ic_val)) if isinstance(ic_val, float) else str(ic_val).strip()

                integration_tag = None
                if 'tag' in col_map:
                    tag_val = row[col_map['tag']]
                    if pd.notna(tag_val):
                        integration_tag = str(int(tag_val)) if isinstance(tag_val, float) else str(tag_val).strip()

                student_id = None
                if 'id' in col_map:
                    id_val = row[col_map['id']]
                    if pd.notna(id_val):
                        student_id = str(id_val).strip()

                try:
                    conn.execute(
                        """INSERT OR REPLACE INTO students
                           (student_id, name, ic_number, class_name, integration_tag)
                           VALUES (?, ?, ?, ?, ?)""",
                        (student_id, name, ic_number, class_name, integration_tag)
                    )
                    imported += 1
                    classes.add(class_name)
                except sqlite3.Error as e:
                    self.logger.warning(f"Skipping student {name}: {e}")
                    skipped += 1

            conn.commit()

            result = {
                'total': len(df),
                'imported': imported,
                'skipped': skipped,
                'classes': len(classes),
            }

            self.logger.info(
                f"Import complete: {imported} students, {len(classes)} classes, "
                f"{skipped} skipped"
            )
            return result

        except Exception as e:
            raise RosterManagerError(f"Import failed: {e}")
        finally:
            conn.close()

    def get_class_roster(self, class_name: str) -> List[Dict[str, Any]]:
        """
        Get all students in a class.

        Args:
            class_name: Class name (e.g., '5 UKM').

        Returns:
            List of student dicts with 'name', 'ic_number', 'integration_tag', 'student_id'.
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT name, ic_number, integration_tag, student_id "
                "FROM students WHERE class_name = ? AND enabled = 1 ORDER BY name",
                (class_name,)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_student_by_tag(self, integration_tag: str) -> Optional[Dict[str, Any]]:
        """
        Look up student by RFID card tag.

        Args:
            integration_tag: The RFID card ID.

        Returns:
            Student dict or None.
        """
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT name, ic_number, class_name, integration_tag, student_id "
                "FROM students WHERE integration_tag = ? AND enabled = 1",
                (integration_tag,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_all_classes(self) -> List[Dict[str, Any]]:
        """
        Get all classes with student counts.

        Returns:
            List of dicts: [{'class_name': '5 UKM', 'student_count': 26}, ...]
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT class_name, COUNT(*) as student_count "
                "FROM students WHERE enabled = 1 "
                "GROUP BY class_name ORDER BY class_name"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_total_students(self) -> int:
        """Get total number of enabled students."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM students WHERE enabled = 1"
            ).fetchone()
            return row['cnt']
        finally:
            conn.close()

    def get_total_classes(self) -> int:
        """Get total number of unique classes."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(DISTINCT class_name) as cnt FROM students WHERE enabled = 1"
            ).fetchone()
            return row['cnt']
        finally:
            conn.close()

    def clear_roster(self) -> int:
        """
        Delete all students from roster.

        Returns:
            Number of students deleted.
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute("DELETE FROM students")
            conn.commit()
            count = cursor.rowcount
            self.logger.info(f"Cleared roster: {count} students deleted")
            return count
        finally:
            conn.close()
