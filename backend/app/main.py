"""FastAPI entry point: API routes plus the built React app on one URL."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.api.datasets import router as datasets_router
from app.api.errors import register_error_handlers
from app.api.sample import log_sample_status

VERSION = "0.1.0"
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

PLACEHOLDER_HTML = (
    "<!doctype html><title>Saabit</title>"
    "<p>Saabit API is running. The frontend has not been built yet.</p>"
)


class Health(BaseModel):
    """Body returned by the health check."""

    status: str
    version: str


def health() -> Health:
    """Report that the service is up and which version is running."""
    return Health(status="ok", version=VERSION)


def placeholder() -> HTMLResponse:
    """Stand-in page for / when frontend/dist does not exist."""
    return HTMLResponse(PLACEHOLDER_HTML)


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built frontend at /, or a placeholder page if it is not built."""
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    else:
        app.add_api_route("/", placeholder, methods=["GET"], include_in_schema=False)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """On startup, only check that the prepared sample cache exists. No data work here."""
    log_sample_status(app)
    yield


def create_app(frontend_dist: Path = FRONTEND_DIST) -> FastAPI:
    """Build the app. API routes are added before the frontend so /api always wins."""
    app = FastAPI(title="Saabit", version=VERSION, lifespan=lifespan)
    register_error_handlers(app)
    app.add_api_route("/api/health", health, methods=["GET"], response_model=Health)
    app.include_router(datasets_router)
    mount_frontend(app, frontend_dist)
    return app


app = create_app()
