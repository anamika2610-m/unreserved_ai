"""
Centralized application exceptions and HTTP error types.

Use these across the app instead of ad-hoc HTTPException or generic Exception.
Register handlers in main.py so these are converted to consistent HTTP responses.

HTTP exceptions (FastAPI-compatible):
  - BadRequestError         400
  - UnauthorizedError       401
  - NotFoundError           404
  - InternalServerError     500
  - ServiceUnavailableError 503
  - RateLimitExceededError  429

Domain exceptions (handled in main.py and mapped to HTTP):
  - ValidationError         → 400
  - DatabaseError           → 500
  - ExternalServiceError    → 502/503
"""
from typing import Any, Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse


# ---------------------------------------------------------------------------
# Base (for single exception handler)
# ---------------------------------------------------------------------------

class AppException(Exception):
    """Base for all app-defined exceptions. Handlers can map to HTTP responses."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        detail: Optional[Any] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail if detail is not None else message


# ---------------------------------------------------------------------------
# HTTP exceptions (subclass HTTPException so FastAPI handles them natively)
# ---------------------------------------------------------------------------

class BadRequestError(HTTPException):
    """400 Bad Request – invalid input, validation failed."""

    def __init__(self, detail: str = "Bad request", **kwargs: Any):
        super().__init__(status_code=400, detail=detail, **kwargs)


class UnauthorizedError(HTTPException):
    """401 Unauthorized – missing or invalid auth."""

    def __init__(self, detail: str = "Unauthorized", **kwargs: Any):
        super().__init__(status_code=401, detail=detail, **kwargs)


class NotFoundError(HTTPException):
    """404 Not Found – resource does not exist."""

    def __init__(self, detail: str = "Not found", **kwargs: Any):
        super().__init__(status_code=404, detail=detail, **kwargs)


class RateLimitExceededError(HTTPException):
    """429 Too Many Requests – rate limit exceeded."""

    def __init__(self, detail: str = "Rate limit exceeded", **kwargs: Any):
        super().__init__(status_code=429, detail=detail, **kwargs)


class InternalServerError(HTTPException):
    """500 Internal Server Error – unexpected server error."""

    def __init__(self, detail: str = "Internal server error", **kwargs: Any):
        super().__init__(status_code=500, detail=detail, **kwargs)


class ServiceUnavailableError(HTTPException):
    """503 Service Unavailable – dependency down or overloaded."""

    def __init__(self, detail: str = "Service unavailable", **kwargs: Any):
        super().__init__(status_code=503, detail=detail, **kwargs)


# ---------------------------------------------------------------------------
# Domain exceptions (raised from services/repos; handler maps to HTTP)
# ---------------------------------------------------------------------------

class ValidationError(AppException):
    """Invalid input or business rule violation → 400."""

    def __init__(self, message: str, detail: Optional[Any] = None):
        super().__init__(message, status_code=400, detail=detail)


class DatabaseError(AppException):
    """DB operation failed → 500."""

    def __init__(self, message: str, detail: Optional[Any] = None):
        super().__init__(message, status_code=500, detail=detail)


class ExternalServiceError(AppException):
    """External API/service failed → 502 or 503."""

    def __init__(
        self,
        message: str,
        status_code: int = 503,
        detail: Optional[Any] = None,
    ):
        super().__init__(message, status_code=status_code, detail=detail)


# ---------------------------------------------------------------------------
# LLM error classification (reusable from RAG pipeline, voice, etc.)
# ---------------------------------------------------------------------------

def classify_llm_error(error: Exception) -> str:
    """
    Classify an LLM/API exception into a known category for handling.

    Returns one of: "rate_limit", "context_length", "timeout", "auth", "model", "unknown".
    """
    msg = str(error).lower()
    error_type_name = type(error).__name__.lower()

    if "429" in msg or "rate_limit" in msg or "rate limit" in msg:
        return "rate_limit"
    if "context_length" in msg or "maximum context" in msg or "context window" in msg:
        return "context_length"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if "authentication" in msg or "api key" in msg or "unauthorized" in msg or "401" in msg:
        return "auth"
    if "permissiondenied" in error_type_name or "403" in msg:
        if "model" in msg or "does not have access" in msg:
            return "model"
        return "auth"
    if "model" in msg and ("not found" in msg or "does not have access" in msg or "not available" in msg):
        return "model"
    return "unknown"


# ---------------------------------------------------------------------------
# Handler for domain exceptions (register in main.py)
# ---------------------------------------------------------------------------

def app_exception_handler(request: Any, exc: AppException) -> JSONResponse:
    """Convert AppException (and subclasses) to a JSONResponse."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail if exc.detail is not None else exc.message},
    )
