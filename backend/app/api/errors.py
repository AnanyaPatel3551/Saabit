"""Turn known exceptions into typed JSON errors with a readable message."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.schemas import ErrorDetail, ErrorOut
from app.core.ingest import UploadError
from app.core.storage import DatasetNotFound


class SampleUnavailable(Exception):
    """The bundled sample file is not present on this server."""

    code = "sample_unavailable"
    message = "The sample dataset is not available on this server."


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
    app.add_exception_handler(RequestValidationError, invalid_request)
