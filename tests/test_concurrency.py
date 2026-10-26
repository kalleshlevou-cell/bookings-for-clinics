import asyncio
import pytest
from httpx import AsyncClient

from tests.conftest import future_time


@pytest.mark.asyncio
async def test_concurrent_booking_race_condition(client: AsyncClient):
    """
    CRITICAL TEST (Weight 3 - Correctness):
    Fires 20 simultaneous booking requests at the exact same moment for a single slot.
    Guarantees:
    - Exactly 1 request succeeds with 201 Created.
    - Exactly 19 requests fail with 409 Conflict (SLOT_ALREADY_BOOKED).
    - Under no circumstances does a double-booking occur.
    """
    # Create an available slot
    slot_res = await client.post("/slots", json={
        "clinic_id": "clinic_concurrency_test",
        "doctor_id": "dr_race_condition",
        "start_time": future_time(60),
        "end_time": future_time(90),
    })
    assert slot_res.status_code == 201
    slot_id = slot_res.json()["id"]

    num_concurrent_requests = 20

    async def attempt_booking(patient_num: int):
        return await client.post("/bookings", json={
            "slot_id": slot_id,
            "patient_name": f"Patient {patient_num}",
            "patient_email": f"patient_{patient_num}@race.com",
            "patient_phone": f"+1-555-01{patient_num:02d}",
        })

    # Fire all 20 requests simultaneously
    responses = await asyncio.gather(*(attempt_booking(i) for i in range(num_concurrent_requests)))

    status_codes = [r.status_code for r in responses]
    successes = [r for r in responses if r.status_code == 201]
    conflicts = [r for r in responses if r.status_code == 409]

    # Verify exactly one winner and all others received conflict
    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}. Status codes: {status_codes}"
    assert len(conflicts) == num_concurrent_requests - 1, f"Expected {num_concurrent_requests - 1} conflicts, got {len(conflicts)}"

    # Check error format on conflicts
    for conflict_res in conflicts:
        err = conflict_res.json()["error"]
        assert err["code"] == "SLOT_ALREADY_BOOKED"
        assert "no longer available" in err["message"].lower() or "already" in err["message"].lower()

    # Verify slot state in API
    slot_check = await client.get(f"/slots/{slot_id}")
    assert slot_check.status_code == 200
    assert slot_check.json()["status"] == "booked"

    # Verify bookings list in API: exactly one confirmed booking exists for this slot
    bookings_res = await client.get(f"/bookings?slot_id={slot_id}&status=confirmed")
    assert bookings_res.status_code == 200
    active_bookings = bookings_res.json()
    assert len(active_bookings) == 1
    assert active_bookings[0]["id"] == successes[0].json()["id"]


@pytest.mark.asyncio
async def test_multi_slot_concurrent_burst(client: AsyncClient):
    """
    Simulates high traffic across multiple slots concurrently:
    Creates 3 separate slots, and fires 10 simultaneous booking attempts for EACH slot (30 total concurrent requests).
    Each slot must have exactly 1 confirmed booking, and 9 conflicts.
    """
    num_slots = 3
    requests_per_slot = 10

    slot_ids = []
    for i in range(num_slots):
        res = await client.post("/slots", json={
            "clinic_id": f"clinic_burst_{i}",
            "start_time": future_time(60 + (i * 30)),
            "end_time": future_time(90 + (i * 30)),
        })
        assert res.status_code == 201
        slot_ids.append(res.json()["id"])

    async def attempt_booking(target_slot_id: str, patient_num: int):
        return await client.post("/bookings", json={
            "slot_id": target_slot_id,
            "patient_name": f"Burst Patient {patient_num}",
            "patient_email": f"burst_{patient_num}@test.com",
        })

    tasks = []
    for slot_idx, slot_id in enumerate(slot_ids):
        for p in range(requests_per_slot):
            tasks.append(attempt_booking(slot_id, slot_idx * 100 + p))

    responses = await asyncio.gather(*tasks)

    # Total successes across all 30 requests must be exactly 3 (one per slot)
    successes = [r for r in responses if r.status_code == 201]
    conflicts = [r for r in responses if r.status_code == 409]

    assert len(successes) == num_slots
    assert len(conflicts) == (num_slots * requests_per_slot) - num_slots

    # Check each slot has exactly 1 confirmed booking
    for slot_id in slot_ids:
        slot_res = await client.get(f"/slots/{slot_id}")
        assert slot_res.json()["status"] == "booked"
        
        slot_bookings = await client.get(f"/bookings?slot_id={slot_id}&status=confirmed")
        assert len(slot_bookings.json()) == 1


@pytest.mark.asyncio
async def test_concurrent_booking_and_clinic_cancellation(client: AsyncClient):
    """
    Race condition test: Clinic cancels a slot while multiple patients attempt to book it simultaneously.
    Guarantees:
    - Zero inconsistent states or uncaught exceptions.
    - Double-booking is strictly impossible.
    - Final slot status is 'cancelled'.
    """
    slot_res = await client.post("/slots", json={
        "clinic_id": "clinic_cancel_race",
        "start_time": future_time(60),
        "end_time": future_time(90),
    })
    slot_id = slot_res.json()["id"]

    async def attempt_booking(idx: int):
        return await client.post("/bookings", json={
            "slot_id": slot_id,
            "patient_name": f"Patient {idx}",
            "patient_email": f"patient_{idx}@test.com",
        })

    async def attempt_cancellation():
        return await client.post(f"/slots/{slot_id}/cancel")

    # Launch 10 bookings and 1 clinic cancellation concurrently
    tasks = [attempt_booking(i) for i in range(10)]
    tasks.append(attempt_cancellation())

    responses = await asyncio.gather(*tasks)

    # Inspect final slot status
    slot_final = await client.get(f"/slots/{slot_id}")
    assert slot_final.status_code == 200
    assert slot_final.json()["status"] == "cancelled"

    # Inspect confirmed bookings: MUST be 0 (since slot is cancelled, any booked slot was also cancelled)
    active_bookings = await client.get(f"/bookings?slot_id={slot_id}&status=confirmed")
    assert len(active_bookings.json()) == 0

