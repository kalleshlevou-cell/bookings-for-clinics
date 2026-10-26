import os
from pydantic import BaseModel


class Settings(BaseModel):
    PROJECT_NAME: str = "Clinic Appointment Booking API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Database path can be overridden via environment variable (e.g. for testing)
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "clinic_booking.db")
    
    # Concurrency and transaction timeout settings
    DB_TIMEOUT: float = 15.0


settings = Settings()
