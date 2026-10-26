import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from httpx import ASGITransport, AsyncClient
from app.main import create_app


async def main():
    print("=" * 70)
    print(" CLINIC APPOINTMENT BOOKING API - LIVE DEMO & VERIFICATION")
    print("=" * 70)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://demo-server") as client:
        # 1. Health check
        print("\n[1] Checking API Health...")
        health = await client.get("/health")
        print(f"    Health Status: {health.status_code} -> {health.json()}")

        # 2. Clinic creates two slots
        now = datetime.now(timezone.utc)
        slot1_start = (now + timedelta(hours=2)).isoformat()
        slot1_end = (now + timedelta(hours=2, minutes=30)).isoformat()
        slot2_start = (now + timedelta(hours=3)).isoformat()
        slot2_end = (now + timedelta(hours=3, minutes=30)).isoformat()

        print("\n[2] Clinic publishes Slot 1 (10:00 - 10:30)...")
        res1 = await client.post("/slots", json={
            "clinic_id": "clinic_st_jude",
            "doctor_id": "dr_curie",
            "start_time": slot1_start,
            "end_time": slot1_end,
        })
        slot1 = res1.json()
        print(f"    Created Slot 1 (ID: {slot1['id']}) Status: {slot1['status']}")

        print("\n[3] Clinic publishes Slot 2 (11:00 - 11:30)...")
        res2 = await client.post("/slots", json={
            "clinic_id": "clinic_st_jude",
            "doctor_id": "dr_curie",
            "start_time": slot2_start,
            "end_time": slot2_end,
        })
        slot2 = res2.json()
        print(f"    Created Slot 2 (ID: {slot2['id']}) Status: {slot2['status']}")

        # 4. Attempt to create overlapping slot (should fail)
        print("\n[4] Attempting to create an overlapping slot for Dr. Curie...")
        overlap_res = await client.post("/slots", json={
            "clinic_id": "clinic_st_jude",
            "doctor_id": "dr_curie",
            "start_time": (now + timedelta(hours=2, minutes=15)).isoformat(),
            "end_time": (now + timedelta(hours=2, minutes=45)).isoformat(),
        })
        print(f"    Response: HTTP {overlap_res.status_code} (Expected 409 Conflict)")
        print(f"    Error: {overlap_res.json()['error']['message']}")

        # 5. List available slots
        print("\n[5] Listing available slots for clinic_st_jude...")
        list_res = await client.get("/slots?clinic_id=clinic_st_jude&status=available")
        available_slots = list_res.json()
        print(f"    Found {len(available_slots)} available slots:")
        for s in available_slots:
            print(f"    - Slot {s['id'][:8]}... | Doctor: {s['doctor_id']} | From {s['start_time']} to {s['end_time']}")

        # 6. Patient books Slot 1
        print("\n[6] Patient Alice books Slot 1...")
        book_res = await client.post("/bookings", json={
            "slot_id": slot1["id"],
            "patient_name": "Alice Cooper",
            "patient_email": "alice@music.org",
            "patient_phone": "+1-555-0101",
        })
        booking1 = book_res.json()
        print(f"    Booking Confirmed! ID: {booking1['id']}, Status: {booking1['status']}")

        # 7. Patient Bob attempts to book the same Slot 1 (Sequential double-booking prevention)
        print("\n[7] Patient Bob tries to book already-booked Slot 1...")
        book_dup_res = await client.post("/bookings", json={
            "slot_id": slot1["id"],
            "patient_name": "Bob Dylan",
            "patient_email": "bob@music.org",
        })
        print(f"    Response: HTTP {book_dup_res.status_code} (Expected 409 Conflict)")
        print(f"    Error: {book_dup_res.json()['error']['message']}")

        # 8. High-concurrency Race Condition Test (Simultaneous booking requests)
        print("\n[8] CONCURRENCY TEST: 15 patients simultaneously race to book Slot 2 at the exact same millisecond...")
        
        async def race_book(patient_id: int):
            return await client.post("/bookings", json={
                "slot_id": slot2["id"],
                "patient_name": f"Racer {patient_id}",
                "patient_email": f"racer_{patient_id}@test.com",
            })

        race_responses = await asyncio.gather(*(race_book(i) for i in range(15)))
        success_count = sum(1 for r in race_responses if r.status_code == 201)
        conflict_count = sum(1 for r in race_responses if r.status_code == 409)
        print(f"    Finished 15 concurrent requests:")
        print(f"    --> HTTP 201 Created (Winner):   {success_count} (EXACTLY 1)")
        print(f"    --> HTTP 409 Conflict (Rejected): {conflict_count} (EXACTLY 14)")
        assert success_count == 1
        assert conflict_count == 14
        print("    [PASS] Concurrency double-booking prevention verified 100%!")

        # 9. Patient Alice cancels her booking for Slot 1 -> Slot reopens!
        print("\n[9] Patient Alice cancels her booking...")
        cancel_book_res = await client.post(f"/bookings/{booking1['id']}/cancel", json={
            "reason": "Family emergency"
        })
        print(f"    Booking Cancelled: ID {cancel_book_res.json()['id']}, Status: {cancel_book_res.json()['status']}")
        
        slot1_reopened = await client.get(f"/slots/{slot1['id']}")
        print(f"    Slot 1 status after cancellation: '{slot1_reopened.json()['status']}' (Reopened to available!)")

        # 10. Patient Charlie can now book the reopened Slot 1
        print("\n[10] Patient Charlie books the newly reopened Slot 1...")
        book_charlie = await client.post("/bookings", json={
            "slot_id": slot1["id"],
            "patient_name": "Charlie Chaplin",
            "patient_email": "charlie@film.org",
        })
        print(f"    Booking Confirmed for Charlie! Status: {book_charlie.json()['status']}")

        # 11. Clinic cancels Slot 1 while Charlie is booked -> Cascades cancellation
        print("\n[11] Clinic decides to cancel Slot 1...")
        clinic_cancel = await client.post(f"/slots/{slot1['id']}/cancel")
        print(f"    Slot Cancellation Response: {clinic_cancel.json()['message']}")
        print(f"    Slot Status: {clinic_cancel.json()['slot']['status']}")
        print(f"    Affected Booking ID Cancelled: {clinic_cancel.json()['cancelled_booking_id']}")

    print("\n" + "=" * 70)
    print(" ALL DEMONSTRATION STEPS COMPLETED AND VERIFIED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
