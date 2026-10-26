from contextlib import asynccontextmanager
from typing import Any, List
import sqlite3

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.exceptions import AppException
from app.db.connection import get_connection
from app.db.schema import init_db
from app.routers import bookings_router, slots_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database schema on startup
    conn = get_connection()
    init_db(conn)
    yield
    # Shutdown logic if needed


def create_app() -> FastAPI:
    # Ensure schema is initialized
    conn = get_connection()
    init_db(conn)

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=(
            "A high-reliability Clinic Appointment Booking API.\n\n"
            "Key features:\n"
            "- Clinics publish, list, and cancel availability time slots\n"
            "- Patients book and cancel appointments\n"
            "- Strict double-booking prevention guaranteed under high concurrency\n"
            "- Comprehensive input validation and structured helpful error responses"
        ),
        lifespan=lifespan,
    )

    # -------------------------------------------------------------
    # Exception Handlers: Standardized, Helpful Error Format
    # -------------------------------------------------------------

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        details: List[dict] = []
        for err in exc.errors():
            loc = err.get("loc", [])
            field_name = " -> ".join([str(x) for x in loc if x not in ("body", "query", "path")])
            msg = err.get("msg", "Invalid value")
            # Strip Pydantic's internal 'Value error, ' prefix if present
            if msg.startswith("Value error, "):
                msg = msg[len("Value error, "):]
            details.append({
                "field": field_name or "body",
                "message": msg,
            })

        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Input validation failed. Please check the provided data.",
                    "details": details,
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": "HTTP_ERROR",
                    "message": exc.detail,
                    "details": None,
                }
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected server error occurred.",
                    "details": str(exc),
                }
            },
        )

    # -------------------------------------------------------------
    # Routers
    # -------------------------------------------------------------
    app.include_router(slots_router)
    app.include_router(bookings_router)

    # -------------------------------------------------------------
    # Health & Meta Endpoints
    # -------------------------------------------------------------
    @app.get("/health", tags=["Health"], summary="API Health Check")
    def health_check():
        try:
            conn = get_connection()
            conn.execute("SELECT 1;").fetchone()
            db_status = "connected"
        except Exception as e:
            db_status = f"unhealthy: {str(e)}"
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "degraded", "database": db_status}
            )

        return {
            "status": "healthy",
            "database": db_status,
            "version": settings.VERSION,
        }

    @app.get("/", tags=["Info"], summary="API Root Info")
    def root():
        return {
            "name": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "docs_url": "/docs",
            "openapi_url": "/openapi.json",
            "endpoints": {
                "slots": "/slots",
                "bookings": "/bookings",
                "health": "/health",
            }
        }

    return app


app = create_app()
