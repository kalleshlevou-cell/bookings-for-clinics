import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.db.connection import transaction
from app.models.schemas import BookingCancelRequest, BookingCreate, BookingResponse, BookingStatus, SlotStatus
from app.repositories.booking_repository import BookingRepository
from app.repositories.slot_repository import SlotRepository


class BookingService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.booking_repo = BookingRepository(conn)
        self.slot_repo = SlotRepository(conn)

    def create_booking(self, data: BookingCreate) -> BookingResponse:
        """
        Books a slot for a patient.
        Guarantees that a slot can never be double-booked, even under simultaneous concurrent requests.
        Enforces atomic status transition and partial unique DB index constraint.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        now_utc = datetime.now(timezone.utc)

        with transaction(self.conn, immediate=True) as cursor:
            # Step 1: Check slot existence
            slot = self.slot_repo.get_by_id(data.slot_id, cursor=cursor)
            if not slot:
                raise NotFoundException(resource="slot", identifier=data.slot_id)

            # Step 2: Validate slot state
            if slot["status"] == SlotStatus.CANCELLED.value:
                raise BadRequestException(
                    code="SLOT_CANCELLED",
                    message=f"Slot '{data.slot_id}' has been cancelled by the clinic and cannot be booked."
                )

            # Step 3: Validate that slot start time has not already passed
            slot_start = datetime.fromisoformat(slot["start_time"])
            if slot_start.tzinfo is None:
                slot_start = slot_start.replace(tzinfo=timezone.utc)
            if slot_start < now_utc:
                raise BadRequestException(
                    code="SLOT_IN_PAST",
                    message="Cannot book an appointment slot whose start time has already passed."
                )

            # Step 4: Check if already booked
            if slot["status"] == SlotStatus.BOOKED.value:
                raise ConflictException(
                    code="SLOT_ALREADY_BOOKED",
                    message=f"Slot '{data.slot_id}' is already booked."
                )

            # Step 5: Atomic update on slot status (Check-and-Set)
            updated = self.slot_repo.atomic_update_status(
                cursor=cursor,
                slot_id=data.slot_id,
                new_status=SlotStatus.BOOKED.value,
                expected_status=SlotStatus.AVAILABLE.value,
                updated_at_iso=now_iso
            )
            if not updated:
                raise ConflictException(
                    code="SLOT_ALREADY_BOOKED",
                    message=f"Slot '{data.slot_id}' is no longer available."
                )

            # Step 6: Create confirmed booking record
            booking_id = str(uuid.uuid4())
            booking_data = {
                "id": booking_id,
                "slot_id": data.slot_id,
                "patient_name": data.patient_name,
                "patient_email": data.patient_email,
                "patient_phone": data.patient_phone,
                "status": BookingStatus.CONFIRMED.value,
                "cancellation_reason": None,
                "created_at": now_iso,
                "updated_at": now_iso,
            }

            try:
                self.booking_repo.create(cursor, booking_data)
            except sqlite3.IntegrityError as e:
                # Unique index on active booking caught concurrent race condition
                raise ConflictException(
                    code="SLOT_ALREADY_BOOKED",
                    message=f"Slot '{data.slot_id}' has already been booked."
                ) from e

        # Retrieve created booking
        created = self.booking_repo.get_by_id(booking_id)
        return BookingResponse(**created)

    def cancel_booking(self, booking_id: str, cancel_data: BookingCancelRequest) -> BookingResponse:
        """
        Cancels an existing booking.
        If the booking is confirmed and the slot is still active, the slot reverts to available.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        now_utc = datetime.now(timezone.utc)

        with transaction(self.conn, immediate=True) as cursor:
            booking = self.booking_repo.get_by_id(booking_id, cursor=cursor)
            if not booking:
                raise NotFoundException(resource="booking", identifier=booking_id)

            if booking["status"] == BookingStatus.CANCELLED.value:
                raise BadRequestException(
                    code="BOOKING_ALREADY_CANCELLED",
                    message=f"Booking '{booking_id}' is already cancelled."
                )

            reason = cancel_data.reason or "Cancelled by patient"
            self.booking_repo.cancel_booking(
                cursor=cursor,
                booking_id=booking_id,
                reason=reason,
                updated_at_iso=now_iso
            )

            # Check associated slot
            slot = self.slot_repo.get_by_id(booking["slot_id"], cursor=cursor)
            if slot and slot["status"] == SlotStatus.BOOKED.value:
                slot_start = datetime.fromisoformat(slot["start_time"])
                if slot_start.tzinfo is None:
                    slot_start = slot_start.replace(tzinfo=timezone.utc)
                
                # Only reopen slot if it is still in the future
                if slot_start >= now_utc:
                    self.slot_repo.atomic_update_status(
                        cursor=cursor,
                        slot_id=booking["slot_id"],
                        new_status=SlotStatus.AVAILABLE.value,
                        updated_at_iso=now_iso
                    )

        updated_booking = self.booking_repo.get_by_id(booking_id)
        return BookingResponse(**updated_booking)

    def get_booking(self, booking_id: str) -> BookingResponse:
        """Retrieves a booking by ID."""
        booking = self.booking_repo.get_by_id(booking_id)
        if not booking:
            raise NotFoundException(resource="booking", identifier=booking_id)
        return BookingResponse(**booking)

    def list_bookings(
        self,
        patient_email: Optional[str] = None,
        slot_id: Optional[str] = None,
        status: Optional[BookingStatus] = None,
    ) -> List[BookingResponse]:
        """Lists bookings matching query filters."""
        status_val = status.value if status else None
        rows = self.booking_repo.list_bookings(
            patient_email=patient_email,
            slot_id=slot_id,
            status=status_val
        )
        return [BookingResponse(**row) for row in rows]
