import sqlite3
import uuid
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.db.connection import transaction
from app.models.schemas import SlotCancelResponse, SlotCreate, SlotResponse, SlotStatus
from app.repositories.booking_repository import BookingRepository
from app.repositories.slot_repository import SlotRepository


class SlotService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.slot_repo = SlotRepository(conn)
        self.booking_repo = BookingRepository(conn)

    def create_slot(self, data: SlotCreate) -> SlotResponse:
        """
        Creates a new clinic time slot.
        Validates non-overlapping constraints and records slot atomically.
        """
        start_utc = data.start_time.astimezone(timezone.utc)
        end_utc = data.end_time.astimezone(timezone.utc)
        start_iso = start_utc.isoformat()
        end_iso = end_utc.isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        # Enforce that start time is in the future
        if start_utc <= datetime.now(timezone.utc):
            raise BadRequestException(
                code="PAST_TIME_SLOT",
                message="Cannot create a slot in the past. Start time must be in the future."
            )

        with transaction(self.conn, immediate=True) as cursor:
            # Check for overlapping active (non-cancelled) slots for this clinic / doctor
            overlapping = self.slot_repo.find_overlapping(
                clinic_id=data.clinic_id,
                doctor_id=data.doctor_id,
                start_time_iso=start_iso,
                end_time_iso=end_iso,
                cursor=cursor
            )

            if overlapping:
                conflict = overlapping[0]
                doctor_info = f" (doctor: {data.doctor_id})" if data.doctor_id else ""
                raise ConflictException(
                    code="SLOT_OVERLAP",
                    message=(
                        f"Cannot create slot. Overlaps with existing slot '{conflict['id']}'{doctor_info} "
                        f"from {conflict['start_time']} to {conflict['end_time']}."
                    ),
                    details={
                        "conflicting_slot_id": conflict["id"],
                        "conflicting_start_time": conflict["start_time"],
                        "conflicting_end_time": conflict["end_time"],
                    }
                )

            slot_id = str(uuid.uuid4())
            slot_data = {
                "id": slot_id,
                "clinic_id": data.clinic_id,
                "doctor_id": data.doctor_id,
                "start_time": start_iso,
                "end_time": end_iso,
                "status": SlotStatus.AVAILABLE.value,
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            self.slot_repo.create(cursor, slot_data)

        # Retrieve freshly created slot
        created = self.slot_repo.get_by_id(slot_id)
        return SlotResponse(**created)

    def get_slot(self, slot_id: str) -> SlotResponse:
        """Retrieves a slot by ID or raises 404."""
        slot = self.slot_repo.get_by_id(slot_id)
        if not slot:
            raise NotFoundException(resource="slot", identifier=slot_id)
        return SlotResponse(**slot)

    def list_slots(
        self,
        clinic_id: Optional[str] = None,
        doctor_id: Optional[str] = None,
        status: Optional[SlotStatus] = None,
        start_time_gte: Optional[datetime] = None,
        end_time_lte: Optional[datetime] = None,
        date_filter: Optional[date] = None,
    ) -> List[SlotResponse]:
        """Lists slots with optional filtering."""
        start_gte_iso = None
        end_lte_iso = None

        if date_filter:
            # Range for whole date in UTC
            start_gte_iso = datetime(
                date_filter.year, date_filter.month, date_filter.day, 0, 0, 0, tzinfo=timezone.utc
            ).isoformat()
            end_lte_iso = datetime(
                date_filter.year, date_filter.month, date_filter.day, 23, 59, 59, 999999, tzinfo=timezone.utc
            ).isoformat()
        else:
            if start_time_gte:
                start_gte_iso = start_time_gte.astimezone(timezone.utc).isoformat()
            if end_time_lte:
                end_lte_iso = end_time_lte.astimezone(timezone.utc).isoformat()

        status_val = status.value if status else None
        rows = self.slot_repo.list_slots(
            clinic_id=clinic_id,
            doctor_id=doctor_id,
            status=status_val,
            start_time_gte=start_gte_iso,
            end_time_lte=end_lte_iso,
        )
        return [SlotResponse(**row) for row in rows]

    def cancel_slot(self, slot_id: str) -> SlotCancelResponse:
        """
        Cancels a time slot.
        - If slot does not exist -> 404
        - If already cancelled -> 400
        - If available -> sets to cancelled
        - If booked -> sets slot to cancelled and marks active booking as cancelled.
        """
        with transaction(self.conn, immediate=True) as cursor:
            slot = self.slot_repo.get_by_id(slot_id, cursor=cursor)
            if not slot:
                raise NotFoundException(resource="slot", identifier=slot_id)

            if slot["status"] == SlotStatus.CANCELLED.value:
                raise BadRequestException(
                    code="SLOT_ALREADY_CANCELLED",
                    message=f"Slot '{slot_id}' is already cancelled."
                )

            now_iso = datetime.now(timezone.utc).isoformat()
            cancelled_booking_id = None

            if slot["status"] == SlotStatus.BOOKED.value:
                # Cancel associated confirmed booking
                cancelled_booking_id = self.booking_repo.cancel_active_booking_for_slot(
                    cursor=cursor,
                    slot_id=slot_id,
                    reason="Slot cancelled by clinic",
                    updated_at_iso=now_iso
                )

            # Update slot status
            self.slot_repo.atomic_update_status(
                cursor=cursor,
                slot_id=slot_id,
                new_status=SlotStatus.CANCELLED.value,
                updated_at_iso=now_iso
            )

        updated_slot = self.slot_repo.get_by_id(slot_id)
        msg = (
            f"Slot cancelled successfully. Associated booking '{cancelled_booking_id}' was also cancelled."
            if cancelled_booking_id
            else "Slot cancelled successfully."
        )
        return SlotCancelResponse(
            slot=SlotResponse(**updated_slot),
            cancelled_booking_id=cancelled_booking_id,
            message=msg
        )
