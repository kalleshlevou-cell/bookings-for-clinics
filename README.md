# Clinic Appointment Booking API

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.162.0-teal.svg)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/Tests-27%20Passed-brightgreen.svg)](https://docs.pytest.org/)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

A high-reliability RESTful API for clinics to publish time slots and patients to book them. Built with **FastAPI**, **Pydantic v2**, and **SQLite (WAL mode)**, engineered specifically to guarantee that **a slot can never be double-booked, even under intense concurrent load**.

---

## Table of Contents

- [Core Features & Business Rules](#core-features--business-rules)
- [Double-Booking & Concurrency Architecture](#double-booking--concurrency-architecture)
- [Architecture & Separation of Concerns](#architecture--separation-of-concerns)
- [Quickstart & Setup](#quickstart--setup)
- [Running the Server](#running-the-server)
- [Interactive API Documentation](#interactive-api-documentation)
- [API Endpoints Reference](#api-endpoints-reference)
- [End-to-End Example Requests (curl & PowerShell)](#end-to-end-example-requests-curl--powershell)
- [Running the Automated Tests](#running-the-automated-tests)
- [Running the Live Interactive Demo](#running-the-live-interactive-demo)
- [Error Handling & Helpful Error Messages](#error-handling--helpful-error-messages)

---

## Core Features & Business Rules

### 1. Slots (Clinic Management)
- **Publish Slots (`POST /slots`)**: Clinics create availability time slots by providing `clinic_id`, optional `doctor_id`, `start_time`, and `end_time`.
- **Validation**:
  - `start_time` must be in the future.
  - `end_time` must be strictly after `start_time` (minimum duration: 5 minutes, maximum: 24 hours).
  - **No Overlapping Slots**: Clinics/doctors cannot publish overlapping active slots. Any overlap is rejected with `409 Conflict`.
- **List & Filter (`GET /slots`)**: Filter by `clinic_id`, `doctor_id`, `status` (`available`, `booked`, `cancelled`), date (`YYYY-MM-DD`), or time ranges (`start_time_gte`, `end_time_lte`).
- **Cancel Slot (`POST /slots/{slot_id}/cancel`)**:
  - If available: status changes to `cancelled`.
  - If booked: cancels the slot AND automatically marks any active confirmed booking as `cancelled` with reason `"Slot cancelled by clinic"`.
  - If already cancelled: returns `400 Bad Request` with `SLOT_ALREADY_CANCELLED`.

### 2. Bookings (Patient Appointments)
- **Book Slot (`POST /bookings` or `POST /slots/{slot_id}/book`)**: Patients book an available slot by providing `slot_id`, `patient_name`, and `patient_email`.
- **Zero Double-Booking Guarantee**: A slot can only ever have at most ONE confirmed booking.
- **Cancel Booking (`POST /bookings/{booking_id}/cancel`)**:
  - Marks booking status as `cancelled`.
  - **Automatic Slot Reopening**: If the cancelled slot is still in the future and wasn't cancelled by the clinic, the slot reverts to `available` so another patient can book it immediately.
  - If already cancelled: returns `400 Bad Request` with `BOOKING_ALREADY_CANCELLED`.
- **List & Filter (`GET /bookings`)**: Query bookings by `patient_email`, `slot_id`, or `status`.

---

## Double-Booking & Concurrency Architecture

Preventing double bookings under concurrent load (e.g. 20 patients hitting the booking button at the exact same millisecond) is achieved using a **multi-layered concurrency defense**:

```
                  Concurrent Booking Requests
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
      Request A                             Request B
            │                                     │
            ▼                                     ▼
 ┌────────────────────────────────────────────────────────┐
 │ Layer 1: In-Process Write Mutex & BEGIN IMMEDIATE      │
 │ Serializes write transactions upfront before mutations │
 └────────────────────────────────────────────────────────┘
            │                                     │
   (Acquires Lock First)                  (Waits for Lock)
            ▼                                     │
 ┌──────────────────────────────────────┐         │
 │ Layer 2: Atomic Check-and-Set UPDATE │         │
 │ UPDATE slots SET status = 'booked'   │         │
 │ WHERE id = ? AND status='available'  │         │
 └──────────────────────────────────────┘         │
            │ (rowcount == 1: Success)            │
            ▼                                     ▼
 ┌──────────────────────────────────────┐ ┌──────────────────────────────────────┐
 │ Layer 3: Partial Unique Index        │ │ Layer 2: Atomic Check-and-Set UPDATE │
 │ UNIQUE(slot_id) WHERE status='conf.' │ │ UPDATE slots SET status = 'booked'   │
 │ INSERT INTO bookings ...             │ │ WHERE id = ? AND status='available'  │
 └──────────────────────────────────────┘ └──────────────────────────────────────┘
            │                                     │ (rowcount == 0: Status was 'booked')
            ▼                                     ▼
       201 Created                           409 Conflict
 (Confirmed Booking)                  ("Slot is already booked")
```

1. **Database-Level Partial Unique Index**:
   ```sql
   CREATE UNIQUE INDEX idx_unique_active_slot_booking
   ON bookings (slot_id) WHERE status = 'confirmed';
   ```
   At the database storage engine layer, SQLite will actively reject any duplicate confirmed booking for the same slot with an `IntegrityError`.
2. **Atomic Status Check-and-Set**:
   ```sql
   UPDATE slots
   SET status = 'booked', updated_at = :now
   WHERE id = :slot_id AND status = 'available';
   ```
   This single atomic statement updates the row only if it is currently `available`. In high concurrency, exactly one transaction updates the row (`cursor.rowcount == 1`). All concurrent contenders match 0 rows and are immediately rejected with `409 Conflict`.
3. **SQLite WAL Mode & `BEGIN IMMEDIATE`**:
   The database runs in Write-Ahead Logging (`WAL`) mode with `PRAGMA busy_timeout = 15000`. Write transactions acquire a reserved lock upfront (`BEGIN IMMEDIATE`) rather than deferring lock acquisition, completely eliminating lock-upgrade deadlocks.
4. **Automated Concurrency Proof**:
   Tested in `tests/test_concurrency.py` with 20 simultaneous requests fired via `asyncio.gather`. Exactly 1 succeeds with `201 Created` and exactly 19 receive `409 Conflict`.

---

## Architecture & Separation of Concerns

The codebase follows clean architectural layering with strict separation of concerns:

```
├── app/
│   ├── core/                  # Configuration, settings & custom domain exceptions
│   │   ├── config.py
│   │   └── exceptions.py
│   ├── db/                    # Database connection manager, WAL pragmas, schema & migrations
│   │   ├── connection.py
│   │   └── schema.py
│   ├── models/                # Pydantic schemas, validation rules, DTOs & response contracts
│   │   └── schemas.py
│   ├── repositories/          # Raw SQL data-access layer with atomic queries & index enforcement
│   │   ├── slot_repository.py
│   │   └── booking_repository.py
│   ├── services/              # Pure business logic, concurrency transitions & validation workflows
│   │   ├── slot_service.py
│   │   └── booking_service.py
│   ├── routers/               # HTTP presentation layer, REST status codes & query parsing
│   │   ├── slots.py
│   │   └── bookings.py
│   └── main.py                # FastAPI app factory, standardized error handlers & health checks
├── scripts/
│   └── demo.py                # Standalone interactive demo verifying all business rules
├── tests/
│   ├── conftest.py            # Test isolation fixtures with temporary SQLite DB & async HTTP client
│   ├── test_slots.py          # Slot lifecycle, overlap checks & past-date validation
│   ├── test_bookings.py       # Booking lifecycle, reopening on cancellation & invalid states
│   ├── test_concurrency.py    # High-concurrency race condition verification (20+ simultaneous requests)
│   └── test_validation.py     # Schema validation, bad input & error formatting
├── requirements.txt           # Locked Python dependencies
├── run.py                     # Convenience server launcher
└── README.md                  # Comprehensive API documentation
```

---

## Quickstart & Setup

### Prerequisites
- Python 3.11+
- Git

### 1. Clone & Navigate to Repository
```bash
git clone <repository_url>
cd <repository_folder>
```

### 2. Set Up Virtual Environment

**On Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**On macOS / Linux (bash/zsh):**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Running the Server

Start the API server with auto-reload:

```bash
python run.py
```

*Or directly with uvicorn:*
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The server will start at `http://localhost:8000`.

---

## Interactive API Documentation

Once the server is running, visit:
- **Swagger UI (Interactive Playground)**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc (Detailed Specifications)**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI JSON Spec**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

---

## API Endpoints Reference

| Method | Endpoint | Description | Status Codes |
|---|---|---|---|
| `GET` | `/health` | API health & database connectivity check | `200`, `503` |
| `POST` | `/slots` | Clinic publishes a new availability time slot | `201`, `400`, `409`, `422` |
| `GET` | `/slots` | List & filter slots (`clinic_id`, `status`, `date`, etc.) | `200` |
| `GET` | `/slots/{slot_id}` | Retrieve details of a specific slot | `200`, `404` |
| `POST` | `/slots/{slot_id}/cancel` | Clinic cancels a slot (and cascades to active booking) | `200`, `400`, `404` |
| `POST` | `/slots/{slot_id}/book` | Direct convenience endpoint to book a slot | `201`, `400`, `404`, `409`, `422` |
| `POST` | `/bookings` | Patient books an available time slot | `201`, `400`, `404`, `409`, `422` |
| `GET` | `/bookings` | List bookings (filter by `patient_email`, `slot_id`, `status`)| `200` |
| `GET` | `/bookings/{booking_id}` | Retrieve details of a specific booking | `200`, `404` |
| `POST` | `/bookings/{booking_id}/cancel` | Patient/Clinic cancels a booking (reopens slot) | `200`, `400`, `404` |

---

## End-to-End Example Requests (curl & PowerShell)

### 1. Health Check
```bash
curl -X GET "http://localhost:8000/health"
```
*Response (`200 OK`):*
```json
{
  "status": "healthy",
  "database": "connected",
  "version": "1.0.0"
}
```

---

### 2. Publish a Time Slot (Clinic)
```bash
curl -X POST "http://localhost:8000/slots" \
  -H "Content-Type: application/json" \
  -d '{
    "clinic_id": "clinic_downtown",
    "doctor_id": "dr_curie",
    "start_time": "2026-11-01T10:00:00Z",
    "end_time": "2026-11-01T10:30:00Z"
  }'
```
*Response (`201 Created`):*
```json
{
  "id": "e838b813-fdf6-4e5a-a384-269bf697a224",
  "clinic_id": "clinic_downtown",
  "doctor_id": "dr_curie",
  "start_time": "2026-11-01T10:00:00Z",
  "end_time": "2026-11-01T10:30:00Z",
  "status": "available",
  "created_at": "2026-10-26T12:00:00Z",
  "updated_at": "2026-10-26T12:00:00Z"
}
```

---

### 3. Overlap Rejection (Clinic cannot publish overlapping slots)
```bash
curl -X POST "http://localhost:8000/slots" \
  -H "Content-Type: application/json" \
  -d '{
    "clinic_id": "clinic_downtown",
    "doctor_id": "dr_curie",
    "start_time": "2026-11-01T10:15:00Z",
    "end_time": "2026-11-01T10:45:00Z"
  }'
```
*Response (`409 Conflict`):*
```json
{
  "error": {
    "code": "SLOT_OVERLAP",
    "message": "Cannot create slot. Overlaps with existing slot 'e838b813-fdf6-4e5a-a384-269bf697a224' (doctor: dr_curie) from 2026-11-01T10:00:00Z to 2026-11-01T10:30:00Z.",
    "details": {
      "conflicting_slot_id": "e838b813-fdf6-4e5a-a384-269bf697a224",
      "conflicting_start_time": "2026-11-01T10:00:00Z",
      "conflicting_end_time": "2026-11-01T10:30:00Z"
    }
  }
}
```

---

### 4. List Available Slots
```bash
curl -X GET "http://localhost:8000/slots?clinic_id=clinic_downtown&status=available"
```

---

### 5. Patient Books the Slot
```bash
curl -X POST "http://localhost:8000/bookings" \
  -H "Content-Type: application/json" \
  -d '{
    "slot_id": "e838b813-fdf6-4e5a-a384-269bf697a224",
    "patient_name": "Alice Cooper",
    "patient_email": "alice@music.org",
    "patient_phone": "+1-555-0100"
  }'
```
*Response (`201 Created`):*
```json
{
  "id": "a1f9e2b0-8dfb-40fa-9eb2-793db5f86663",
  "slot_id": "e838b813-fdf6-4e5a-a384-269bf697a224",
  "patient_name": "Alice Cooper",
  "patient_email": "alice@music.org",
  "patient_phone": "+1-555-0100",
  "status": "confirmed",
  "cancellation_reason": null,
  "created_at": "2026-10-26T12:05:00Z",
  "updated_at": "2026-10-26T12:05:00Z"
}
```

---

### 6. Reject Double-Booking Attempt
```bash
curl -X POST "http://localhost:8000/bookings" \
  -H "Content-Type: application/json" \
  -d '{
    "slot_id": "e838b813-fdf6-4e5a-a384-269bf697a224",
    "patient_name": "Bob Dylan",
    "patient_email": "bob@music.org"
  }'
```
*Response (`409 Conflict`):*
```json
{
  "error": {
    "code": "SLOT_ALREADY_BOOKED",
    "message": "Slot 'e838b813-fdf6-4e5a-a384-269bf697a224' is already booked.",
    "details": null
  }
}
```

---

### 7. Patient Cancels Booking (Reopening the Slot)
```bash
curl -X POST "http://localhost:8000/bookings/a1f9e2b0-8dfb-40fa-9eb2-793db5f86663/cancel" \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Rescheduled meeting"
  }'
```
*Response (`200 OK`):*
```json
{
  "id": "a1f9e2b0-8dfb-40fa-9eb2-793db5f86663",
  "slot_id": "e838b813-fdf6-4e5a-a384-269bf697a224",
  "patient_name": "Alice Cooper",
  "patient_email": "alice@music.org",
  "status": "cancelled",
  "cancellation_reason": "Rescheduled meeting",
  "updated_at": "2026-10-26T12:10:00Z"
}
```
*Note: Slot `e838b813...` status automatically reverts back to `available`.*

---

### 8. Clinic Cancels Slot
```bash
curl -X POST "http://localhost:8000/slots/e838b813-fdf6-4e5a-a384-269bf697a224/cancel"
```
*Response (`200 OK`):*
```json
{
  "slot": {
    "id": "e838b813-fdf6-4e5a-a384-269bf697a224",
    "status": "cancelled"
  },
  "cancelled_booking_id": null,
  "message": "Slot cancelled successfully."
}
```

---

## Running the Automated Tests

The automated test suite contains **27 tests** covering all business rules, input validations, edge cases, and high-concurrency race condition scenarios.

Run pytest:

```bash
pytest -v
```

### Test Suite Structure:
- `tests/test_concurrency.py`:
  - `test_concurrent_booking_race_condition`: Fires 20 simultaneous requests at the exact same millisecond. Proves exactly 1 winner (`201`) and 19 conflicts (`409`).
  - `test_multi_slot_concurrent_burst`: 30 concurrent requests across 3 slots (10 per slot).
  - `test_concurrent_booking_and_clinic_cancellation`: Race condition between booking and cancellation.
- `tests/test_bookings.py`:
  - Slot booking, sequential duplicate prevention, reopening slot on booking cancel, non-existent slots, and invalid states.
- `tests/test_slots.py`:
  - Slot creation, start time in past rejected, end time before start rejected, overlap detection, adjacent slot allowance, slot cancellation and cascading booking cancellation.
- `tests/test_validation.py`:
  - Malformed email address, blank fields, missing JSON payload, and structured error formatting.

---

## Running the Live Interactive Demo

We have included a standalone script that runs an interactive, step-by-step demonstration verifying all requirements:

```bash
python scripts/demo.py
```

This will run through:
1. Health check verification
2. Publishing valid slots
3. Overlap conflict rejection
4. Filtering available slots
5. Booking a slot
6. Sequential double-booking rejection (409)
7. **15-request simultaneous concurrency race test (proving 1 winner, 14 conflicts)**
8. Patient cancellation reopening the slot
9. New patient booking the reopened slot
10. Clinic cancellation cascading to active booking

---

## Error Handling & Helpful Error Messages

All errors are returned in a uniform, structured JSON format with descriptive codes and actionable messages:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Input validation failed. Please check the provided data.",
    "details": [
      {
        "field": "patient_email",
        "message": "Invalid email address format."
      }
    ]
  }
}
```

### Standard Error Codes:
- `VALIDATION_ERROR` (`422`): Malformed input, missing fields, or invalid formats.
- `SLOT_NOT_FOUND` (`404`): Slot does not exist.
- `BOOKING_NOT_FOUND` (`404`): Booking does not exist.
- `SLOT_ALREADY_BOOKED` (`409`): Attempt to book an already occupied slot.
- `SLOT_OVERLAP` (`409`): Attempt to publish an overlapping slot for the same clinic/doctor.
- `SLOT_CANCELLED` (`400`): Attempt to book a cancelled slot.
- `SLOT_ALREADY_CANCELLED` (`400`): Attempt to cancel a slot that is already cancelled.
- `BOOKING_ALREADY_CANCELLED` (`400`): Attempt to cancel a booking that is already cancelled.
- `PAST_TIME_SLOT` (`400`/`422`): Slot start time cannot be in the past.
