import sqlite3


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS slots (
    id TEXT PRIMARY KEY,
    clinic_id TEXT NOT NULL,
    doctor_id TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('available', 'booked', 'cancelled')) DEFAULT 'available',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_slots_clinic_time ON slots (clinic_id, start_time, end_time);
CREATE INDEX IF NOT EXISTS idx_slots_status ON slots (status);

CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY,
    slot_id TEXT NOT NULL,
    patient_name TEXT NOT NULL,
    patient_email TEXT NOT NULL,
    patient_phone TEXT,
    status TEXT NOT NULL CHECK(status IN ('confirmed', 'cancelled')) DEFAULT 'confirmed',
    cancellation_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (slot_id) REFERENCES slots(id) ON DELETE RESTRICT
);

-- Crucial: Partial unique index guaranteeing at the database engine level that NO two confirmed bookings can ever exist for the same slot.
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_active_slot_booking ON bookings (slot_id) WHERE status = 'confirmed';

CREATE INDEX IF NOT EXISTS idx_bookings_patient_email ON bookings (patient_email);
CREATE INDEX IF NOT EXISTS idx_bookings_slot_id ON bookings (slot_id);
"""


def init_db(conn: sqlite3.Connection) -> None:
    """Initializes tables and indexes."""
    conn.executescript(SCHEMA_SQL)
