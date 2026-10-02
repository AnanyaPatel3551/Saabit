"""Turn known exceptions into typed JSON errors with a readable message.

Anything unexpected becomes one generic 500 with a request id; the full error and traceback
go only to the server log, never to the user.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.observe import SECURITY_HEADERS
from app.api.schemas import ErrorDetail, ErrorOut
from app.core.compile_sql import QueryTimeout
from app.core.evidence import CardNotFound
from app.core.ingest import UploadError
from app.core.pipeline import DatasetNotReady
from app.core.plan import PlanError
from app.core.storage import DatasetNotFound


class SampleUnavailable(Exception):
    """The sample cannot be served: its file or its prepared cache is missing."""

    code = "sample_unavailable"
    default_message = "The sample dataset is not available on this server."

    def __init__(self, message: str = default_message) -> None:
        self.message = message
        super().__init__(message)


class ApiError(Exception):
    """An error with its own HTTP status, code and user-readable message."""

    status_code = 400
    code = "api_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class InvalidRoles(ApiError):
    code = "invalid_roles"


class Forbidden(ApiError):
    status_code = 403
    code = "forbidden"


class NotCleaned(ApiError):
    status_code = 409
    code = "not_cleaned"


class RateLimited(ApiError):
    """Too many requests from one client (PRD Abuse); retry_after is in seconds."""

    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMPaused(ApiError):
    """The planner's model is unreachable; typed questions pause (PRD Degraded mode)."""

    status_code = 503
    code = "llm_unavailable"


logger = logging.getLogger(__name__)
INTERNAL_MESSAGE = "Something went wrong on our side. Reference: {request_id}."


def error_response(status_code: int, code: str, message: str,
                   headers: dict[str, str] | None = None) -> JSONResponse:
    body = ErrorOut(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump(), headers=headers)


async def upload_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, UploadError)
    return error_response(400, exc.code, exc.message)


async def dataset_not_found(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DatasetNotFound)
    return error_response(404, exc.code, exc.message)


async def sample_unavailable(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, SampleUnavailable)
    return error_response(503, exc.code, exc.message)


async def api_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    headers = {"Retry-After": str(exc.retry_after)} if isinstance(exc, RateLimited) else None
    return error_response(exc.status_code, exc.code, exc.message, headers)


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Last resort: log everything, tell the user only that it failed and the reference."""
    request_id = request_id_of(request)
    logger.error("unhandled error request_id=%s path=%s", request_id, request.url.path,
                 exc_info=exc)
    # This response is built outside the middleware, so it adds the security headers itself.
    return error_response(500, "internal_error", INTERNAL_MESSAGE.format(request_id=request_id),
                          {"X-Request-ID": request_id, **SECURITY_HEADERS})


# Errors raised by core modules (which know nothing about HTTP) and the status each maps to.
CORE_ERROR_STATUS: dict[type[Exception], int] = {
    PlanError: 400,
    DatasetNotReady: 409,
    CardNotFound: 404,
    QueryTimeout: 504,
}


async def core_error(_: Request, exc: Exception) -> JSONResponse:
    status = next(s for kind, s in CORE_ERROR_STATUS.items() if isinstance(exc, kind))
    return error_response(status, exc.code, exc.message)  # type: ignore[attr-defined]


async def invalid_request(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    fields = ", ".join(".".join(str(p) for p in err["loc"]) for err in exc.errors())
    message = f"The request is missing or has invalid fields: {fields}."
    return error_response(422, "invalid_request", message)


def register_error_handlers(app: FastAPI) -> None:
    """Attach every handler so no stack trace reaches the user."""
    app.add_exception_handler(UploadError, upload_error)
    app.add_exception_handler(DatasetNotFound, dataset_not_found)
    app.add_exception_handler(SampleUnavailable, sample_unavailable)
    app.add_exception_handler(ApiError, api_error)
    for kind in CORE_ERROR_STATUS:
        app.add_exception_handler(kind, core_error)
    app.add_exception_handler(RequestValidationError, invalid_request)
    app.add_exception_handler(Exception, unexpected_error)
