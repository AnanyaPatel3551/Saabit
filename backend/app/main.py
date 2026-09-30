"""FastAPI entry point: API routes plus the built React app on one URL."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.api.cards import router as cards_router
from app.api.datasets import router as datasets_router
from app.api.errors import register_error_handlers
from app.api.sample import log_sample_status
from app.llm.config import status_dict

VERSION = "0.1.0"
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

PLACEHOLDER_HTML = (
    "<!doctype html><title>Saabit</title>"
    "<p>Saabit API is running. The frontend has not been built yet.</p>"
)


class LLMHealth(BaseModel):
    """Last known LLM state. Health checks never call the LLM; this is the latest outcome."""

    provider: str
    model: str
    status: str  # ok, unavailable, not_configured or unknown
    reason: str | None
    checked_at: str | None


class Health(BaseModel):
    """Body returned by the health check."""

    status: str
    version: str
    llm: LLMHealth


def health() -> Health:
    """Report that the service is up, its version, and the LLM's last known state."""
    return Health(status="ok", version=VERSION, llm=LLMHealth(**status_dict()))


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
    app.include_router(cards_router)
    mount_frontend(app, frontend_dist)
    return app


app = create_app()
