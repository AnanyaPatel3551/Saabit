"""The bundled sample dataset: prepared once (at image build), then read from a small cache."""

import hashlib
import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI

from app.api.errors import SampleUnavailable
from app.api.schemas import DatasetOut
from app.api.shared import clean_loaded, describe
from app.core import detect, ingest

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_PATH = REPO_ROOT / "data" / "sample" / "amazon_sale_report.csv.gz"
SAMPLE_CACHE_ENV = "SAABIT_SAMPLE_CACHE"
DEFAULT_SAMPLE_CACHE = Path(__file__).resolve().parents[2] / "sample_cache"
METADATA_FILE = "metadata.json"
SAMPLE_ID_LENGTH = 12  # same shape as random dataset ids (storage.ID_PATTERN)
SAMPLE_ROLES: dict[str, str] = {
    "order_id": "Order ID",
    "order_date": "Date",
    "amount": "Amount",
    "status": "Status",
    "state": "ship-state",
    "city": "ship-city",
    "category": "Category",
    "sku": "SKU",
    "fulfilment": "Fulfilment",
    "qty": "Qty",
    "channel": "Sales Channel",
}

logger = logging.getLogger(__name__)


def get_sample_path() -> Path:
    """Where the bundled sample lives. Overridden in tests."""
    return SAMPLE_PATH


def get_sample_cache_dir() -> Path:
    """Where the prepared sample metadata lives (SAABIT_SAMPLE_CACHE). Overridden in tests."""
    return Path(os.environ.get(SAMPLE_CACHE_ENV) or DEFAULT_SAMPLE_CACHE)


def sample_id(sample_path: Path) -> str:
    """First 12 hex characters of the file's SHA-256, hashed in 1 MB chunks."""
    digest = hashlib.sha256()
    with sample_path.open("rb") as f:
        while chunk := f.read(ingest.CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()[:SAMPLE_ID_LENGTH]


def read_cached_sample(cache_dir: Path) -> DatasetOut | None:
    """The prepared sample metadata, or None if it has not been prepared."""
    path = cache_dir / METADATA_FILE
    if not path.is_file():
        return None
    return DatasetOut.model_validate_json(path.read_text(encoding="utf-8"))


def build_sample_cache(sample_path: Path, cache_dir: Path) -> DatasetOut:
    """Scan and clean the sample once; write metadata.json, clean.parquet and fixes.csv.

    The file is read a single time for cleaning; the header, sample values and row check
    come from that same load, and DuckDB gives the whole-file row count.
    """
    if not sample_path.is_file():
        raise SampleUnavailable()
    cache_dir.mkdir(parents=True, exist_ok=True)
    names, delimiter = ingest.header_names(sample_path)
    rows = ingest.count_rows(sample_path, delimiter)
    raw, skipped = ingest.load_rows(sample_path, list(SAMPLE_ROLES.values()))
    columns = [n.strip() for n in names]
    detection = detect.confirmed_roles(raw, SAMPLE_ROLES, columns)
    dataset_id = sample_id(sample_path)
    dataset = describe(
        dataset_id, sample_path.name, sample_path.stat().st_size, rows, columns,
        detection, confirmed=True,
    )
    # Hand the only reference to clean_loaded, so the raw rows are freed as soon as it is done.
    owned = [raw]
    del raw
    dataset.data_check = clean_loaded(dataset_id, owned.pop(), skipped, SAMPLE_ROLES, cache_dir)
    payload = json.dumps(dataset.model_dump(mode="json"), ensure_ascii=False, indent=2)
    (cache_dir / METADATA_FILE).write_text(payload, encoding="utf-8")
    return dataset


NOT_PREPARED = (
    "The sample dataset has not been prepared on this server. "
    "Run 'python -m app.prepare_sample' (the Docker build does this automatically)."
)


def shared_sample(cache_dir: Path) -> DatasetOut:
    """The one shared sample, read from its prepared cache.

    Never builds or cleans the sample inside a request: that work belongs to the image
    build (python -m app.prepare_sample). A missing cache is a 503.
    """
    cached = read_cached_sample(cache_dir)
    if cached is None:
        raise SampleUnavailable(NOT_PREPARED)
    return cached


def log_sample_status(app: FastAPI) -> None:
    """Startup check: read the small cache file only. Never parses the sample."""
    cache_dir = app.dependency_overrides.get(get_sample_cache_dir, get_sample_cache_dir)()
    cached = read_cached_sample(cache_dir)
    if cached is None:
        logger.warning("sample cache not found in %s; run python -m app.prepare_sample", cache_dir)
    else:
        logger.info("sample ready from cache: %s (%d rows)", cached.dataset_id, cached.rows)
