import sqlite3
from typing import Any, Dict, List, Optional
from datetime import datetime


class BookingRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create(self, cursor: sqlite3.Cursor, booking_data: Dict[str, Any]) -> Dict[str, Any]:
        """Inserts a new booking. Protected by partial unique index on slot_id where status='confirmed'."""
        query = """
        INSERT INTO bookings (id, slot_id, patient_name, patient_email, patient_phone, status, cancellation_reason, created_at, updated_at)
        VALUES (:id, :slot_id, :patient_name, :patient_email, :patient_phone, :status, :cancellation_reason, :created_at, :updated_at)
        """
        cursor.execute(query, booking_data)
        return booking_data

    def get_by_id(self, booking_id: str, cursor: Optional[sqlite3.Cursor] = None) -> Optional[Dict[str, Any]]:
        """Retrieves a booking by ID."""
        target = cursor if cursor is not None else self.conn
        query = "SELECT * FROM bookings WHERE id = ?"
        cur = target.execute(query, (booking_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_active_by_slot_id(self, slot_id: str, cursor: Optional[sqlite3.Cursor] = None) -> Optional[Dict[str, Any]]:
        """Retrieves the active (confirmed) booking for a slot, if any exists."""
        target = cursor if cursor is not None else self.conn
        query = "SELECT * FROM bookings WHERE slot_id = ? AND status = 'confirmed'"
        cur = target.execute(query, (slot_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_bookings(
        self,
        patient_email: Optional[str] = None,
        slot_id: Optional[str] = None,
        status: Optional[str] = None,
        cursor: Optional[sqlite3.Cursor] = None
    ) -> List[Dict[str, Any]]:
        """Lists bookings matching filters, ordered by created_at descending."""
        target = cursor if cursor is not None else self.conn
        query = "SELECT * FROM bookings WHERE 1=1"
        params: List[Any] = []

        if patient_email:
            query += " AND LOWER(patient_email) = LOWER(?)"
            params.append(patient_email.strip())
        if slot_id:
            query += " AND slot_id = ?"
            params.append(slot_id)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC"
        cur = target.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

    def cancel_booking(
        self,
        cursor: sqlite3.Cursor,
        booking_id: str,
        reason: str,
        updated_at_iso: Optional[str] = None
    ) -> bool:
        """Marks a booking as cancelled with a reason."""
        updated_at = updated_at_iso or datetime.now().isoformat()
        query = """
        UPDATE bookings
        SET status = 'cancelled', cancellation_reason = ?, updated_at = ?
        WHERE id = ? AND status = 'confirmed'
        """
        cursor.execute(query, (reason, updated_at, booking_id))
        return cursor.rowcount > 0

    def cancel_active_booking_for_slot(
        self,
        cursor: sqlite3.Cursor,
        slot_id: str,
        reason: str,
        updated_at_iso: Optional[str] = None
    ) -> Optional[str]:
        """
        Cancels any confirmed booking for the given slot.
        Returns the ID of the cancelled booking, or None if no active booking was found.
        """
        updated_at = updated_at_iso or datetime.now().isoformat()
        # Find active booking first
        active = self.get_active_by_slot_id(slot_id, cursor=cursor)
        if not active:
            return None
        
        booking_id = active["id"]
        cursor.execute(
            """
            UPDATE bookings
            SET status = 'cancelled', cancellation_reason = ?, updated_at = ?
            WHERE id = ? AND status = 'confirmed'
            """,
            (reason, updated_at, booking_id)
        )
        return booking_id
