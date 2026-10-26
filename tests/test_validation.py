import pytest
from httpx import AsyncClient

from tests.conftest import future_time


@pytest.mark.asyncio
async def test_invalid_email_format(client: AsyncClient):
    """Providing a malformed email address returns a clear 422 error with details."""
    slot_res = await client.post("/slots", json={
        "clinic_id": "clinic_val",
        "start_time": future_time(60),
        "end_time": future_time(90),
    })
    slot_id = slot_res.json()["id"]

    # Invalid email
    res = await client.post("/bookings", json={
        "slot_id": slot_id,
        "patient_name": "John Doe",
        "patient_email": "not-an-email-at-all",
    })
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert any("email" in d["message"].lower() or d["field"] == "patient_email" for d in err["details"])


@pytest.mark.asyncio
async def test_missing_required_fields_in_slot(client: AsyncClient):
    """Missing required fields in slot creation returns structured 422 validation error."""
    res = await client.post("/slots", json={})
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    fields = [d["field"] for d in err["details"]]
    assert "clinic_id" in fields
    assert "start_time" in fields
    assert "end_time" in fields


@pytest.mark.asyncio
async def test_blank_clinic_id(client: AsyncClient):
    """Blank or whitespace-only clinic_id is rejected."""
    res = await client.post("/slots", json={
        "clinic_id": "   ",
        "start_time": future_time(60),
        "end_time": future_time(90),
    })
    assert res.status_code == 422
    err = res.json()["error"]
    assert any("clinic_id" in d["field"] for d in err["details"])


@pytest.mark.asyncio
async def test_missing_required_fields_in_booking(client: AsyncClient):
    """Missing required fields in booking creation returns structured 422 error."""
    res = await client.post("/bookings", json={})
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    fields = [d["field"] for d in err["details"]]
    assert "slot_id" in fields
    assert "patient_name" in fields
    assert "patient_email" in fields


@pytest.mark.asyncio
async def test_health_check_endpoint(client: AsyncClient):
    """Health check endpoint returns healthy status and DB connectivity."""
    res = await client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


@pytest.mark.asyncio
async def test_root_endpoint_metadata(client: AsyncClient):
    """Root endpoint returns metadata and documentation paths."""
    res = await client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert "docs_url" in data
    assert "endpoints" in data
