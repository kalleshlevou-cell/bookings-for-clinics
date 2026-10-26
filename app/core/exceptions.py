from typing import Any, Optional


class AppException(Exception):
    """Base exception for all application-level errors."""
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[Any] = None
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


class NotFoundException(AppException):
    def __init__(self, resource: str, identifier: str):
        super().__init__(
            status_code=404,
            code=f"{resource.upper()}_NOT_FOUND",
            message=f"{resource.capitalize()} with identifier '{identifier}' was not found."
        )


class ConflictException(AppException):
    def __init__(self, code: str, message: str, details: Optional[Any] = None):
        super().__init__(
            status_code=409,
            code=code,
            message=message,
            details=details
        )


class BadRequestException(AppException):
    def __init__(self, code: str, message: str, details: Optional[Any] = None):
        super().__init__(
            status_code=400,
            code=code,
            message=message,
            details=details
        )
