from typing import List, Optional
import sqlite3

from fastapi import APIRouter, Depends, Query, status

from app.db.connection import get_db
from app.models.schemas import (
    BookingCancelRequest,
    BookingCreate,
    BookingResponse,
    BookingStatus,
)
from app.services.booking_service import BookingService

router = APIRouter(prefix="/bookings", tags=["Bookings"])


def get_booking_service(conn: sqlite3.Connection = Depends(get_db)) -> BookingService:
    return BookingService(conn)


@router.post(
    "",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Book an appointment slot",
    description="Patients book an available clinic time slot. Concurrency-safe: guarantees no double-booking even under simultaneous requests."
)
def create_booking(
    payload: BookingCreate,
    service: BookingService = Depends(get_booking_service),
) -> BookingResponse:
    return service.create_booking(payload)


@router.get(
    "",
    response_model=List[BookingResponse],
    status_code=status.HTTP_200_OK,
    summary="List and filter bookings",
    description="List appointments with optional filtering by patient email, slot ID, or booking status."
)
def list_bookings(
    patient_email: Optional[str] = Query(None, description="Filter by patient email"),
    slot_id: Optional[str] = Query(None, description="Filter by slot ID"),
    status: Optional[BookingStatus] = Query(None, description="Filter by booking status (confirmed, cancelled)"),
    service: BookingService = Depends(get_booking_service),
) -> List[BookingResponse]:
    return service.list_bookings(
        patient_email=patient_email,
        slot_id=slot_id,
        status=status,
    )


@router.get(
    "/{booking_id}",
    response_model=BookingResponse,
    status_code=status.HTTP_200_OK,
    summary="Get booking details",
    description="Retrieve details of a specific appointment booking."
)
def get_booking(
    booking_id: str,
    service: BookingService = Depends(get_booking_service),
) -> BookingResponse:
    return service.get_booking(booking_id)


@router.post(
    "/{booking_id}/cancel",
    response_model=BookingResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel an appointment booking",
    description="Patients or clinics cancel an existing confirmed booking. Reopens the slot for other patients if the slot is still in the future."
)
def cancel_booking(
    booking_id: str,
    payload: Optional[BookingCancelRequest] = None,
    service: BookingService = Depends(get_booking_service),
) -> BookingResponse:
    request_data = payload or BookingCancelRequest()
    return service.cancel_booking(booking_id, request_data)
