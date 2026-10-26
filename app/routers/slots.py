
from datetime import date, datetime
from typing import List, Optional
import sqlite3

from fastapi import APIRouter, Depends, Query, status

from app.db.connection import get_db
from app.models.schemas import (
    BookingCreate,
    BookingResponse,
    SlotCancelResponse,
    SlotCreate,
    SlotResponse,
    SlotStatus,
)
from app.services.booking_service import BookingService
from app.services.slot_service import SlotService

router = APIRouter(prefix="/slots", tags=["Slots"])


def get_slot_service(conn: sqlite3.Connection = Depends(get_db)) -> SlotService:
    return SlotService(conn)


def get_booking_service(conn: sqlite3.Connection = Depends(get_db)) -> BookingService:
    return BookingService(conn)


@router.post(
    "",
    response_model=SlotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Publish a new clinic time slot",
    description="Clinics publish availability time slots. Enforces non-overlapping slots and future start time."
)
def create_slot(
    payload: SlotCreate,
    service: SlotService = Depends(get_slot_service),
) -> SlotResponse:
    return service.create_slot(payload)


@router.get(
    "",
    response_model=List[SlotResponse],
    status_code=status.HTTP_200_OK,
    summary="List and filter time slots",
    description="List published slots with optional filtering by clinic, doctor, status, date, or time window."
)
def list_slots(
    clinic_id: Optional[str] = Query(None, description="Filter by clinic identifier"),
    doctor_id: Optional[str] = Query(None, description="Filter by doctor identifier"),
    status: Optional[SlotStatus] = Query(None, description="Filter by status (available, booked, cancelled)"),
    start_time_gte: Optional[datetime] = Query(None, description="Filter slots starting at or after this ISO datetime"),
    end_time_lte: Optional[datetime] = Query(None, description="Filter slots ending at or before this ISO datetime"),
    date: Optional[date] = Query(None, description="Filter slots for a specific date (YYYY-MM-DD)"),
    service: SlotService = Depends(get_slot_service),
) -> List[SlotResponse]:
    return service.list_slots(
        clinic_id=clinic_id,
        doctor_id=doctor_id,
        status=status,
        start_time_gte=start_time_gte,
        end_time_lte=end_time_lte,
        date_filter=date,
    )


@router.get(
    "/{slot_id}",
    response_model=SlotResponse,
    status_code=status.HTTP_200_OK,
    summary="Get slot details",
    description="Retrieve details of a specific time slot by its ID."
)
def get_slot(
    slot_id: str,
    service: SlotService = Depends(get_slot_service),
) -> SlotResponse:
    return service.get_slot(slot_id)


@router.post(
    "/{slot_id}/cancel",
    response_model=SlotCancelResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel a time slot",
    description="Clinics cancel a time slot. If the slot is already booked, the active booking is also cancelled automatically."
)
def cancel_slot(
    slot_id: str,
    service: SlotService = Depends(get_slot_service),
) -> SlotCancelResponse:
    return service.cancel_slot(slot_id)


class SlotBookPatientPayload(BookingCreate):
    slot_id: Optional[str] = None  # Inferred from path


@router.post(
    "/{slot_id}/book",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Book a slot directly",
    description="Convenience endpoint to book a specific slot by slot ID in the path."
)
def book_slot_by_path(
    slot_id: str,
    patient_info: BookingCreate,
    booking_service: BookingService = Depends(get_booking_service),
) -> BookingResponse:
    # Ensure slot_id in body matches path
    patient_info.slot_id = slot_id
    return booking_service.create_booking(patient_info)
