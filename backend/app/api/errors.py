"""Turn known exceptions into typed JSON errors with a readable message."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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


class NotCleaned(ApiError):
    status_code = 409
    code = "not_cleaned"


class LLMPaused(ApiError):
    """The planner's model is unreachable; typed questions pause (PRD Degraded mode)."""

    status_code = 503
    code = "llm_unavailable"


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorOut(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump())


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
    return error_response(exc.status_code, exc.code, exc.message)


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
