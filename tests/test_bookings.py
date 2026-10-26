import pytest
from httpx import AsyncClient

from tests.conftest import future_time


@pytest.mark.asyncio
async def test_create_booking_success(client: AsyncClient):
    """Test standard booking of an available slot."""
    # Create slot
    slot_res = await client.post("/slots", json={
        "clinic_id": "clinic_1",
        "start_time": future_time(60),
        "end_time": future_time(90),
    })
    slot_id = slot_res.json()["id"]

    # Book slot
    book_res = await client.post("/bookings", json={
        "slot_id": slot_id,
        "patient_name": "Jane Doe",
        "patient_email": "jane@example.com",
        "patient_phone": "+1-555-0100",
    })
    assert book_res.status_code == 201
    booking = book_res.json()
    assert booking["slot_id"] == slot_id
    assert booking["patient_name"] == "Jane Doe"
    assert booking["patient_email"] == "jane@example.com"
    assert booking["status"] == "confirmed"

    # Verify slot status is now 'booked'
    slot_check = await client.get(f"/slots/{slot_id}")
    assert slot_check.json()["status"] == "booked"


@pytest.mark.asyncio
async def test_cannot_double_book_sequential(client: AsyncClient):
    """A slot cannot be booked again once booked."""
    slot_res = await client.post("/slots", json={
        "clinic_id": "clinic_1",
        "start_time": future_time(60),
        "end_time": future_time(90),
    })
    slot_id = slot_res.json()["id"]

    # First booking succeeds
    book1 = await client.post("/bookings", json={
        "slot_id": slot_id,
        "patient_name": "First Patient",
        "patient_email": "first@example.com",
    })
    assert book1.status_code == 201

    # Second booking must fail with 409 Conflict
    book2 = await client.post("/bookings", json={
        "slot_id": slot_id,
        "patient_name": "Second Patient",
        "patient_email": "second@example.com",
    })
    assert book2.status_code == 409
    err = book2.json()["error"]
    assert err["code"] == "SLOT_ALREADY_BOOKED"
    assert "already booked" in err["message"].lower()


@pytest.mark.asyncio
async def test_cannot_book_cancelled_slot(client: AsyncClient):
    """Attempting to book a cancelled slot must fail with 400 Bad Request."""
    slot_res = await client.post("/slots", json={
        "clinic_id": "clinic_1",
        "start_time": future_time(60),
        "end_time": future_time(90),
    })
    slot_id = slot_res.json()["id"]

    # Cancel slot
    await client.post(f"/slots/{slot_id}/cancel")

    # Attempt booking
    book_res = await client.post("/bookings", json={
        "slot_id": slot_id,
        "patient_name": "Patient X",
        "patient_email": "patientx@example.com",
    })
    assert book_res.status_code == 400
    err = book_res.json()["error"]
    assert err["code"] == "SLOT_CANCELLED"
    assert "cancelled by the clinic" in err["message"].lower()


@pytest.mark.asyncio
async def test_cannot_book_non_existent_slot(client: AsyncClient):
    """Attempting to book an unknown slot ID returns 404."""
    book_res = await client.post("/bookings", json={
        "slot_id": "invalid-uuid-12345",
        "patient_name": "Nobody",
        "patient_email": "nobody@example.com",
    })
    assert book_res.status_code == 404
    err = book_res.json()["error"]
    assert err["code"] == "SLOT_NOT_FOUND"


@pytest.mark.asyncio
async def test_direct_booking_via_slot_path(client: AsyncClient):
    """Convenience endpoint POST /slots/{slot_id}/book works identically."""
    slot_res = await client.post("/slots", json={
        "clinic_id": "clinic_1",
        "start_time": future_time(60),
        "end_time": future_time(90),
    })
    slot_id = slot_res.json()["id"]

    book_res = await client.post(f"/slots/{slot_id}/book", json={
        "slot_id": slot_id,
        "patient_name": "Direct Booker",
        "patient_email": "direct@example.com",
    })
    assert book_res.status_code == 201
    assert book_res.json()["slot_id"] == slot_id
    assert book_res.json()["status"] == "confirmed"


@pytest.mark.asyncio
async def test_cancel_booking_and_slot_reopening(client: AsyncClient):
    """
    When a patient cancels their booking, the slot becomes 'available' again
    and another patient can immediately book it.
    """
    slot_res = await client.post("/slots", json={
        "clinic_id": "clinic_reopen",
        "start_time": future_time(60),
        "end_time": future_time(90),
    })
    slot_id = slot_res.json()["id"]

    # Book slot
    book1 = await client.post("/bookings", json={
        "slot_id": slot_id,
        "patient_name": "Patient 1",
        "patient_email": "p1@example.com",
    })
    booking1_id = book1.json()["id"]

    # Cancel booking
    cancel_res = await client.post(
        f"/bookings/{booking1_id}/cancel",
        json={"reason": "Schedule conflict"}
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"
    assert cancel_res.json()["cancellation_reason"] == "Schedule conflict"

    # Verify slot reopened to 'available'
    slot_check = await client.get(f"/slots/{slot_id}")
    assert slot_check.json()["status"] == "available"

    # Patient 2 can now book the reopened slot
    book2 = await client.post("/bookings", json={
        "slot_id": slot_id,
        "patient_name": "Patient 2",
        "patient_email": "p2@example.com",
    })
    assert book2.status_code == 201
    assert book2.json()["status"] == "confirmed"


@pytest.mark.asyncio
async def test_cancel_already_cancelled_booking_fails(client: AsyncClient):
    """Cancelling a booking that is already cancelled returns 400 Bad Request."""
    slot_res = await client.post("/slots", json={
        "clinic_id": "clinic_1",
        "start_time": future_time(60),
        "end_time": future_time(90),
    })
    slot_id = slot_res.json()["id"]

    book = await client.post("/bookings", json={
        "slot_id": slot_id,
        "patient_name": "Patient 1",
        "patient_email": "p1@example.com",
    })
    booking_id = book.json()["id"]

    # First cancel succeeds
    await client.post(f"/bookings/{booking_id}/cancel")

    # Second cancel fails
    cancel2 = await client.post(f"/bookings/{booking_id}/cancel")
    assert cancel2.status_code == 400
    assert cancel2.json()["error"]["code"] == "BOOKING_ALREADY_CANCELLED"


@pytest.mark.asyncio
async def test_list_and_filter_bookings(client: AsyncClient):
    """Listing bookings filtered by patient email or status."""
    # Slot 1
    s1 = await client.post("/slots", json={
        "clinic_id": "clinic_1",
        "start_time": future_time(60),
        "end_time": future_time(90),
    })
    # Slot 2
    s2 = await client.post("/slots", json={
        "clinic_id": "clinic_1",
        "start_time": future_time(120),
        "end_time": future_time(150),
    })

    # Book for Alice
    await client.post("/bookings", json={
        "slot_id": s1.json()["id"],
        "patient_name": "Alice",
        "patient_email": "alice@hospital.org",
    })
    # Book for Bob
    await client.post("/bookings", json={
        "slot_id": s2.json()["id"],
        "patient_name": "Bob",
        "patient_email": "bob@hospital.org",
    })

    # Filter by Alice's email
    alice_res = await client.get("/bookings?patient_email=alice@hospital.org")
    assert len(alice_res.json()) == 1
    assert alice_res.json()[0]["patient_name"] == "Alice"

    # Filter by slot_id
    slot_res = await client.get(f"/bookings?slot_id={s2.json()['id']}")
    assert len(slot_res.json()) == 1
    assert slot_res.json()[0]["patient_name"] == "Bob"
