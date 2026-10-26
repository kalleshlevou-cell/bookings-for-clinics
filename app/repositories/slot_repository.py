import sqlite3
from typing import Any, Dict, List, Optional
from datetime import datetime


class SlotRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create(self, cursor: sqlite3.Cursor, slot_data: Dict[str, Any]) -> Dict[str, Any]:
        """Inserts a new slot."""
        query = """
        INSERT INTO slots (id, clinic_id, doctor_id, start_time, end_time, status, created_at, updated_at)
        VALUES (:id, :clinic_id, :doctor_id, :start_time, :end_time, :status, :created_at, :updated_at)
        """
        cursor.execute(query, slot_data)
        return slot_data

    def get_by_id(self, slot_id: str, cursor: Optional[sqlite3.Cursor] = None) -> Optional[Dict[str, Any]]:
        """Retrieves a slot by ID."""
        target = cursor if cursor is not None else self.conn
        query = "SELECT * FROM slots WHERE id = ?"
        cur = target.execute(query, (slot_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def find_overlapping(
        self,
        clinic_id: str,
        doctor_id: Optional[str],
        start_time_iso: str,
        end_time_iso: str,
        cursor: Optional[sqlite3.Cursor] = None
    ) -> List[Dict[str, Any]]:
        """
        Finds any non-cancelled slots that overlap with the given time window for the same clinic and doctor.
        Two intervals [A_start, A_end) and [B_start, B_end) overlap iff:
        A_start < B_end AND A_end > B_start
        """
        target = cursor if cursor is not None else self.conn
        params = [clinic_id, end_time_iso, start_time_iso]
        
        # If doctor_id is provided, match doctor_id. If doctor_id is None, match clinic slots where doctor_id is NULL
        if doctor_id:
            query = """
            SELECT * FROM slots
            WHERE clinic_id = ?
              AND doctor_id = ?
              AND status != 'cancelled'
              AND start_time < ?
              AND end_time > ?
            """
            params = [clinic_id, doctor_id, end_time_iso, start_time_iso]
        else:
            query = """
            SELECT * FROM slots
            WHERE clinic_id = ?
              AND (doctor_id IS NULL OR doctor_id = '')
              AND status != 'cancelled'
              AND start_time < ?
              AND end_time > ?
            """
            params = [clinic_id, end_time_iso, start_time_iso]
            
        cur = target.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

    def list_slots(
        self,
        clinic_id: Optional[str] = None,
        doctor_id: Optional[str] = None,
        status: Optional[str] = None,
        start_time_gte: Optional[str] = None,
        end_time_lte: Optional[str] = None,
        cursor: Optional[sqlite3.Cursor] = None
    ) -> List[Dict[str, Any]]:
        """Lists slots matching filters, ordered by start_time ascending."""
        target = cursor if cursor is not None else self.conn
        query = "SELECT * FROM slots WHERE 1=1"
        params: List[Any] = []

        if clinic_id:
            query += " AND clinic_id = ?"
            params.append(clinic_id)
        if doctor_id:
            query += " AND doctor_id = ?"
            params.append(doctor_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        if start_time_gte:
            query += " AND start_time >= ?"
            params.append(start_time_gte)
        if end_time_lte:
            query += " AND end_time <= ?"
            params.append(end_time_lte)

        query += " ORDER BY start_time ASC"
        cur = target.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

    def atomic_update_status(
        self,
        cursor: sqlite3.Cursor,
        slot_id: str,
        new_status: str,
        expected_status: Optional[str] = None,
        updated_at_iso: Optional[str] = None
    ) -> bool:
        """
        Atomically updates the status of a slot.
        If expected_status is provided, the update succeeds ONLY if the current status matches.
        Returns True if a row was updated, False otherwise.
        """
        updated_at = updated_at_iso or datetime.now().isoformat()
        if expected_status is not None:
            query = """
            UPDATE slots
            SET status = ?, updated_at = ?
            WHERE id = ? AND status = ?
            """
            cursor.execute(query, (new_status, updated_at, slot_id, expected_status))
        else:
            query = """
            UPDATE slots
            SET status = ?, updated_at = ?
            WHERE id = ?
            """
            cursor.execute(query, (new_status, updated_at, slot_id))
        return cursor.rowcount > 0
