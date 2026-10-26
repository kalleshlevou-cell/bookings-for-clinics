from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient

from tests.conftest import future_time


@pytest.mark.asyncio
async def test_create_slot_success(client: AsyncClient):
    """Test creating a valid clinic time slot."""
    start = future_time(60)
    end = future_time(90)
    payload = {
        "clinic_id": "clinic_central",
        "doctor_id": "dr_smith",
        "start_time": start,
        "end_time": end,
    }
    response = await client.post("/slots", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["clinic_id"] == "clinic_central"
    assert data["doctor_id"] == "dr_smith"
    assert data["status"] == "available"
    assert "id" in data
    assert data["start_time"] is not None
    assert data["end_time"] is not None


@pytest.mark.asyncio
async def test_create_slot_past_time_fails(client: AsyncClient):
    """Slots starting in the past must be rejected."""
    past_start = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    past_end = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    payload = {
        "clinic_id": "clinic_central",
        "start_time": past_start,
        "end_time": past_end,
    }
    response = await client.post("/slots", json=payload)
    assert response.status_code in (400, 422)
    err = response.json()["error"]
    assert "past" in str(err).lower()


@pytest.mark.asyncio
async def test_create_slot_end_before_start_fails(client: AsyncClient):
    """Slot where end_time <= start_time must be rejected with helpful error."""
    start = future_time(120)
    end = future_time(60)
    payload = {
        "clinic_id": "clinic_central",
        "start_time": start,
        "end_time": end,
    }
    response = await client.post("/slots", json=payload)
    assert response.status_code == 422
    err = response.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert any("strictly after start_time" in d["message"] for d in err["details"])


@pytest.mark.asyncio
async def test_create_slot_duration_too_short(client: AsyncClient):
    """Slot duration under 5 minutes must be rejected."""
    start = future_time(60)
    end = (datetime.fromisoformat(start) + timedelta(minutes=2)).isoformat()
    payload = {
        "clinic_id": "clinic_central",
        "start_time": start,
        "end_time": end,
    }
    response = await client.post("/slots", json=payload)
    assert response.status_code == 422
    err = response.json()["error"]
    assert any("at least 5 minutes" in d["message"] for d in err["details"])


@pytest.mark.asyncio
async def test_create_slot_overlap_rejected(client: AsyncClient):
    """Overlapping slots for the same clinic and doctor must be rejected with 409 Conflict."""
    start1 = future_time(60)
    end1 = future_time(120)
    slot1_payload = {
        "clinic_id": "clinic_east",
        "doctor_id": "dr_jones",
        "start_time": start1,
        "end_time": end1,
    }
    res1 = await client.post("/slots", json=slot1_payload)
    assert res1.status_code == 201

    # Attempt to create an overlapping slot: starts 30 mins after start1, ends 30 mins after end1
    start2 = future_time(90)
    end2 = future_time(150)
    slot2_payload = {
        "clinic_id": "clinic_east",
        "doctor_id": "dr_jones",
        "start_time": start2,
        "end_time": end2,
    }
    res2 = await client.post("/slots", json=slot2_payload)
    assert res2.status_code == 409
    err = res2.json()["error"]
    assert err["code"] == "SLOT_OVERLAP"
    assert "overlaps with existing slot" in err["message"].lower()


@pytest.mark.asyncio
async def test_create_slot_adjacent_and_different_clinic_allowed(client: AsyncClient):
    """Adjacent slots (no overlap) and slots at different clinics are allowed."""
    start1 = future_time(60)
    end1 = future_time(90)
    await client.post("/slots", json={
        "clinic_id": "clinic_east",
        "doctor_id": "dr_jones",
        "start_time": start1,
        "end_time": end1,
    })

    # Adjacent slot starting right at end1
    start2 = end1
    end2 = future_time(120)
    res2 = await client.post("/slots", json={
        "clinic_id": "clinic_east",
        "doctor_id": "dr_jones",
        "start_time": start2,
        "end_time": end2,
    })
    assert res2.status_code == 201

    # Overlapping time but different clinic is allowed
    res3 = await client.post("/slots", json={
        "clinic_id": "clinic_west",
        "doctor_id": "dr_jones",
        "start_time": start1,
        "end_time": end1,
    })
    assert res3.status_code == 201


@pytest.mark.asyncio
async def test_create_slot_allowed_if_previous_overlapping_slot_cancelled(client: AsyncClient):
    """If an overlapping slot was cancelled, a new slot in that window can be published."""
    start = future_time(60)
    end = future_time(90)
    res = await client.post("/slots", json={
        "clinic_id": "clinic_north",
        "start_time": start,
        "end_time": end,
    })
    slot_id = res.json()["id"]

    # Cancel the slot
    cancel_res = await client.post(f"/slots/{slot_id}/cancel")
    assert cancel_res.status_code == 200

    # Publish new slot in exact same time range
    res2 = await client.post("/slots", json={
        "clinic_id": "clinic_north",
        "start_time": start,
        "end_time": end,
    })
    assert res2.status_code == 201


@pytest.mark.asyncio
async def test_list_and_filter_slots(client: AsyncClient):
    """Test listing and filtering slots by clinic, status, and time."""
    start1 = future_time(60)
    end1 = future_time(90)
    await client.post("/slots", json={
        "clinic_id": "clinic_A",
        "start_time": start1,
        "end_time": end1,
    })

    start2 = future_time(120)
    end2 = future_time(150)
    res2 = await client.post("/slots", json={
        "clinic_id": "clinic_B",
        "start_time": start2,
        "end_time": end2,
    })
    slot2_id = res2.json()["id"]

    # List all
    all_res = await client.get("/slots")
    assert len(all_res.json()) == 2

    # Filter by clinic
    filtered = await client.get("/slots?clinic_id=clinic_A")
    assert len(filtered.json()) == 1
    assert filtered.json()[0]["clinic_id"] == "clinic_A"

    # Filter by status
    await client.post(f"/slots/{slot2_id}/cancel")
    avail = await client.get("/slots?status=available")
    assert len(avail.json()) == 1
    canc = await client.get("/slots?status=cancelled")
    assert len(canc.json()) == 1


@pytest.mark.asyncio
async def test_cancel_slot_rules(client: AsyncClient):
    """Test slot cancellation rules."""
    start = future_time(60)
    end = future_time(90)
    res = await client.post("/slots", json={
        "clinic_id": "clinic_C",
        "start_time": start,
        "end_time": end,
    })
    slot_id = res.json()["id"]

    # Cancel available slot
    cancel_res = await client.post(f"/slots/{slot_id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["slot"]["status"] == "cancelled"

    # Cancel already cancelled slot -> 400
    cancel_again = await client.post(f"/slots/{slot_id}/cancel")
    assert cancel_again.status_code == 400
    assert cancel_again.json()["error"]["code"] == "SLOT_ALREADY_CANCELLED"

    # Cancel non-existent slot -> 404
    non_existent = await client.post("/slots/non_existent_uuid/cancel")
    assert non_existent.status_code == 404
    assert non_existent.json()["error"]["code"] == "SLOT_NOT_FOUND"


@pytest.mark.asyncio
async def test_cancel_booked_slot_cancels_booking(client: AsyncClient):
    """When a clinic cancels a slot that is booked, the booking is also cancelled automatically."""
    start = future_time(60)
    end = future_time(90)
    res = await client.post("/slots", json={
        "clinic_id": "clinic_D",
        "start_time": start,
        "end_time": end,
    })
    slot_id = res.json()["id"]

    # Book slot
    book_res = await client.post("/bookings", json={
        "slot_id": slot_id,
        "patient_name": "Bob Patient",
        "patient_email": "bob@example.com",
    })
    assert book_res.status_code == 201
    booking_id = book_res.json()["id"]

    # Clinic cancels slot
    cancel_slot_res = await client.post(f"/slots/{slot_id}/cancel")
    assert cancel_slot_res.status_code == 200
    cancel_data = cancel_slot_res.json()
    assert cancel_data["slot"]["status"] == "cancelled"
    assert cancel_data["cancelled_booking_id"] == booking_id

    # Verify booking status is now cancelled
    get_booking = await client.get(f"/bookings/{booking_id}")
    assert get_booking.status_code == 200
    assert get_booking.json()["status"] == "cancelled"
    assert "Slot cancelled by clinic" in get_booking.json()["cancellation_reason"]
