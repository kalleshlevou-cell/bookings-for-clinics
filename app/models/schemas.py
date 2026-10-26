from datetime import datetime, timezone, date
from enum import Enum
from typing import Any, List, Optional
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SlotStatus(str, Enum):
    AVAILABLE = "available"
    BOOKED = "booked"
    CANCELLED = "cancelled"


class BookingStatus(str, Enum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


# ==========================================
# Error Response Models
# ==========================================

class ErrorDetail(BaseModel):
    field: Optional[str] = None
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# ==========================================
# Slot Models
# ==========================================

class SlotCreate(BaseModel):
    clinic_id: str = Field(..., min_length=1, max_length=100, description="Unique identifier for the clinic", examples=["clinic_downtown_1"])
    doctor_id: Optional[str] = Field(None, max_length=100, description="Optional identifier for the specific doctor", examples=["dr_smith"])
    start_time: datetime = Field(..., description="Slot start time in ISO 8601 UTC", examples=["2026-11-01T09:00:00Z"])
    end_time: datetime = Field(..., description="Slot end time in ISO 8601 UTC", examples=["2026-11-01T09:30:00Z"])

    @field_validator("clinic_id")
    @classmethod
    def validate_clinic_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("clinic_id cannot be blank.")
        return v

    @field_validator("start_time", "end_time")
    @classmethod
    def ensure_timezone_aware(cls, v: datetime) -> datetime:
        # If naive datetime provided, interpret as UTC
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        else:
            v = v.astimezone(timezone.utc)
        return v

    @model_validator(mode="after")
    def validate_time_range(self) -> "SlotCreate":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be strictly after start_time.")
        
        duration_minutes = (self.end_time - self.start_time).total_seconds() / 60.0
        if duration_minutes < 5:
            raise ValueError("Slot duration must be at least 5 minutes.")
        if duration_minutes > 1440:  # 24 hours
            raise ValueError("Slot duration cannot exceed 24 hours.")
        
        # Check that slot is not in the past
        now = datetime.now(timezone.utc)
        if self.start_time < now:
            raise ValueError("start_time cannot be in the past.")

        return self


class SlotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    clinic_id: str
    doctor_id: Optional[str] = None
    start_time: datetime
    end_time: datetime
    status: SlotStatus
    created_at: datetime
    updated_at: datetime


class SlotCancelResponse(BaseModel):
    slot: SlotResponse
    cancelled_booking_id: Optional[str] = None
    message: str


# ==========================================
# Booking Models
# ==========================================

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class BookingCreate(BaseModel):
    slot_id: str = Field(..., min_length=1, description="ID of the slot to book", examples=["slot_abc123"])
    patient_name: str = Field(..., min_length=1, max_length=150, description="Full name of patient", examples=["Alice Wonderland"])
    patient_email: str = Field(..., min_length=3, max_length=255, description="Email address for confirmation", examples=["alice@example.com"])
    patient_phone: Optional[str] = Field(None, max_length=50, description="Optional phone number", examples=["+1-555-0199"])

    @field_validator("patient_name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("patient_name cannot be blank.")
        return v

    @field_validator("patient_email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_REGEX.match(v):
            raise ValueError("Invalid email address format.")
        return v


class BookingCancelRequest(BaseModel):
    reason: Optional[str] = Field("Cancelled by patient", max_length=255, description="Reason for cancellation")


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slot_id: str
    patient_name: str
    patient_email: str
    patient_phone: Optional[str] = None
    status: BookingStatus
    cancellation_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
