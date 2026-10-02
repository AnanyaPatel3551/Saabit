"""FastAPI entry point: API routes plus the built React app on one URL."""

import asyncio
import logging
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.api import observe
from app.api.cards import router as cards_router
from app.api.datasets import get_storage_root
from app.api.datasets import router as datasets_router
from app.api.errors import register_error_handlers
from app.api.evalsummary import router as eval_router
from app.api.ratelimit import RateLimiter
from app.api.sample import get_sample_cache_dir, log_sample_status, read_cached_sample
from app.core import retention, storage
from app.llm.config import status_dict

VERSION = "0.1.0"
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
RETENTION_INTERVAL_S = 3600
PAGES = ("/how-we-test",)
logger = logging.getLogger(__name__)

PLACEHOLDER_HTML = (
    "<!doctype html><title>Saabit</title>"
    "<p>Saabit API is running. The frontend has not been built yet.</p>"
)


class ProviderHealth(BaseModel):
    """One LLM provider in fallback order; cooling_until is set after a long rate limit."""

    name: str
    model: str
    configured: bool
    cooling_until: str | None


class LLMHealth(BaseModel):
    """Last known LLM state. Health checks never call the LLM; this is the latest outcome."""

    provider: str
    model: str
    status: str  # ok, unavailable, not_configured or unknown
    reason: str | None
    checked_at: str | None
    providers: list[ProviderHealth] = []
    state: str = "unknown"  # last call: ok (first provider), fallback, down; unknown before any


class StorageHealth(BaseModel):
    """Free space where datasets are stored."""

    free_mb: int | None


class Health(BaseModel):
    """Body returned by the health check."""

    status: str
    version: str
    llm: LLMHealth
    storage: StorageHealth


def free_mb(folder: Path) -> int | None:
    """Free disk space for the folder (or its nearest existing parent), in MB."""
    for candidate in (folder, *folder.resolve().parents):
        if candidate.exists():
            return shutil.disk_usage(candidate).free // (1024 * 1024)
    return None


def health() -> Health:
    """Report that the service is up, its version, the LLM's last known state and free space."""
    return Health(status="ok", version=VERSION, llm=LLMHealth(**status_dict()),
                  storage=StorageHealth(free_mb=free_mb(storage.storage_root())))


def placeholder() -> HTMLResponse:
    """Stand-in page for / when frontend/dist does not exist."""
    return HTMLResponse(PLACEHOLDER_HTML)


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built frontend at /, or a placeholder page if it is not built."""
    index = dist / "index.html"
    if index.is_file():
        # Pages the app draws itself, so a reload or a shared link still finds them.
        for page in PAGES:
            app.add_api_route(page, lambda: FileResponse(index), methods=["GET"],
                              include_in_schema=False)
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    else:
        app.add_api_route("/", placeholder, methods=["GET"], include_in_schema=False)


def run_retention(app: FastAPI) -> None:
    """One retention sweep over the storage folder, keeping the shared sample's folder."""
    root = app.dependency_overrides.get(get_storage_root, get_storage_root)()
    cache = app.dependency_overrides.get(get_sample_cache_dir, get_sample_cache_dir)()
    sample = read_cached_sample(cache)
    retention.sweep(root, sample.dataset_id if sample else None, storage.plan_cache_dir())


async def retention_loop(app: FastAPI) -> None:
    """Sweep at startup, then every hour. A failed sweep is logged and retried next hour."""
    while True:
        try:
            await asyncio.to_thread(run_retention, app)
        except Exception:
            logger.exception("retention sweep failed")
        await asyncio.sleep(RETENTION_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Check the prepared sample cache exists and start the hourly retention sweep."""
    log_sample_status(app)
    task = asyncio.create_task(retention_loop(app))
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def create_app(frontend_dist: Path = FRONTEND_DIST) -> FastAPI:
    """Build the app. API routes are added before the frontend so /api always wins."""
    app = FastAPI(title="Saabit", version=VERSION, lifespan=lifespan)
    app.state.limiter = RateLimiter()
    observe.install(app)
    register_error_handlers(app)
    app.add_api_route("/api/health", health, methods=["GET"], response_model=Health)
    app.include_router(datasets_router)
    app.include_router(cards_router)
    app.include_router(eval_router)
    mount_frontend(app, frontend_dist)
    return app


app = create_app()
