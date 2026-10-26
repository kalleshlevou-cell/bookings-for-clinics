import sqlite3
import threading
from contextlib import contextmanager
from typing import Generator
from app.core.config import settings

# Thread-local storage for SQLite connections so each thread has its own connection
_thread_local = threading.local()

# Mutex for process-internal serialization of write operations to ensure smooth concurrency
_db_write_lock = threading.Lock()


def get_raw_connection(db_path: str = None) -> sqlite3.Connection:
    """Creates and configures a SQLite connection with WAL mode and sensible timeouts."""
    path = db_path or settings.DATABASE_PATH
    conn = sqlite3.connect(
        path,
        timeout=settings.DB_TIMEOUT,
        check_same_thread=False,
        isolation_level=None  # Managed manually via BEGIN / COMMIT
    )
    conn.row_factory = sqlite3.Row
    
    # Configure pragmas for performance and concurrency
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute(f"PRAGMA busy_timeout = {int(settings.DB_TIMEOUT * 1000)};")
    return conn


def get_connection(db_path: str = None) -> sqlite3.Connection:
    """Returns a connection for the current thread."""
    path = db_path or settings.DATABASE_PATH
    # Check if current thread has an active connection for this path
    conn_attr = f"_conn_{path}"
    conn = getattr(_thread_local, conn_attr, None)
    if conn is None:
        conn = get_raw_connection(path)
        setattr(_thread_local, conn_attr, conn)
    return conn


def get_db(db_path: str = None) -> Generator[sqlite3.Connection, None, None]:
    """Dependency yielding a configured SQLite connection for request lifecycle."""
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        pass


@contextmanager
def transaction(conn: sqlite3.Connection, immediate: bool = True) -> Generator[sqlite3.Cursor, None, None]:
    """
    Context manager for atomic database transactions.
    Uses BEGIN IMMEDIATE for write transactions to acquire the reserved lock upfront,
    preventing deadlocks between concurrent writers.
    Also acquires an in-process write lock to cleanly serialize concurrent threads.
    """
    cursor = conn.cursor()
    if immediate:
        with _db_write_lock:
            cursor.execute("BEGIN IMMEDIATE;")
            try:
                yield cursor
                cursor.execute("COMMIT;")
            except Exception:
                cursor.execute("ROLLBACK;")
                raise
            finally:
                cursor.close()
    else:
        cursor.execute("BEGIN;")
        try:
            yield cursor
            cursor.execute("COMMIT;")
        except Exception:
            cursor.execute("ROLLBACK;")
            raise
        finally:
            cursor.close()
