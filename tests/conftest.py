import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Generator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.db.connection import get_connection, _thread_local
from app.db.schema import init_db
from app.main import create_app


@pytest.fixture(scope="session")
def test_db_path() -> Generator[str, None, None]:
    """Creates a temporary SQLite file for the test session."""
    fd, path = tempfile.mkstemp(suffix="_test.db")
    os.close(fd)
    
    # Override settings database path
    settings.DATABASE_PATH = path
    
    # Initialize schema
    conn = get_connection(path)
    init_db(conn)
    
    yield path
    
    # Teardown: close any connections and remove file
    try:
        conn.close()
    except Exception:
        pass
    for ext in ["", "-wal", "-shm"]:
        p = f"{path}{ext}"
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


@pytest.fixture(autouse=True)
def clean_database(test_db_path: str):
    """Cleans tables before each test to maintain strict isolation."""
    conn = get_connection(test_db_path)
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute("DELETE FROM bookings;")
    conn.execute("DELETE FROM slots;")
    conn.execute("PRAGMA foreign_keys = ON;")
    yield


@pytest.fixture
def app_instance(test_db_path: str):
    """Creates a FastAPI app configured for the test database."""
    return create_app()


@pytest_asyncio.fixture
async def client(app_instance) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for testing API endpoints."""
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def future_time(minutes_from_now: int) -> str:
    """Helper to return an ISO 8601 UTC timestamp N minutes in the future."""
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)
    return dt.isoformat()
