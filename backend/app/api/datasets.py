"""Dataset routes: upload, load the sample, read metadata and roles."""

import hashlib
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, FastAPI, UploadFile

from app.api.errors import SampleUnavailable
from app.api.schemas import DatasetOut, RoleOut
from app.core import detect, ingest, storage

SAMPLE_PATH = Path(__file__).resolve().parents[3] / "data" / "sample" / "amazon_sale_report.csv.gz"
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

SAMPLE_ID_LENGTH = 12  # same shape as random dataset ids (storage.ID_PATTERN)

logger = logging.getLogger(__name__)
sample_lock = threading.Lock()
router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def get_storage_root() -> Path:
    """Where dataset folders live. Overridden in tests."""
    return storage.storage_root()


def get_sample_path() -> Path:
    """Where the bundled sample lives. Overridden in tests."""
    return SAMPLE_PATH


StorageRoot = Annotated[Path, Depends(get_storage_root)]
SamplePath = Annotated[Path, Depends(get_sample_path)]


def describe(
    dataset_id: str, filename: str, size_bytes: int, df: pd.DataFrame,
    detection: detect.DetectionResult, confirmed: bool,
) -> DatasetOut:
    """Build the metadata record for a parsed dataset."""
    return DatasetOut(
        dataset_id=dataset_id,
        filename=filename,
        size_bytes=size_bytes,
        rows=len(df),
        created_at=datetime.now(UTC),
        columns=[str(c) for c in df.columns],
        roles=[RoleOut.model_validate(r) for r in detection.roles],
        roles_confirmed=confirmed,
        missing_required=detection.missing_required,
        unmapped_columns=detection.unmapped_columns,
    )


def sample_id(sample_path: Path) -> str:
    """Fixed id for the sample: the first 12 hex characters of the file's SHA-256.

    The same file always gets the same id, so restarts reuse the stored sample; a new
    sample file gets a new id instead of silently reusing stale metadata.
    """
    return hashlib.sha256(sample_path.read_bytes()).hexdigest()[:SAMPLE_ID_LENGTH]


def build_sample(root: Path, sample_path: Path, dataset_id: str) -> DatasetOut:
    """Parse the bundled sample once and store its metadata. The raw file is not copied."""
    df = ingest.read_bundled_file(sample_path)
    detection = detect.confirmed_roles(df, SAMPLE_ROLES)
    size = sample_path.stat().st_size
    dataset = describe(dataset_id, sample_path.name, size, df, detection, confirmed=True)
    storage.create_dataset_dir(root, dataset_id)
    storage.write_metadata(root, dataset_id, dataset.model_dump(mode="json"))
    return dataset


def shared_sample(root: Path, sample_path: Path) -> DatasetOut:
    """The one shared sample dataset: built on first use (or at startup), then reused."""
    if not sample_path.is_file():
        raise SampleUnavailable()
    dataset_id = sample_id(sample_path)
    with sample_lock:
        try:
            return DatasetOut.model_validate(storage.read_metadata(root, dataset_id))
        except storage.DatasetNotFound:
            return build_sample(root, sample_path, dataset_id)


def preload_sample(app: FastAPI) -> None:
    """Build the shared sample at startup (PRD: sample dataset preloaded at startup)."""
    overrides = app.dependency_overrides
    root = overrides.get(get_storage_root, get_storage_root)()
    sample_path = overrides.get(get_sample_path, get_sample_path)()
    try:
        dataset = shared_sample(root, sample_path)
        logger.info("sample dataset ready: %s (%d rows)", dataset.dataset_id, dataset.rows)
    except SampleUnavailable:
        logger.warning("sample file not found at %s; 'Try sample data' is disabled", sample_path)


@router.post("", response_model=DatasetOut)
def upload_dataset(file: UploadFile, root: StorageRoot) -> DatasetOut:
    """Upload a CSV/XLSX; returns the dataset id and suggested roles (not yet confirmed)."""
    data = file.file.read(ingest.MAX_BYTES + 1)
    filename = file.filename or ""
    df = ingest.read_upload(data, filename)
    dataset_id = storage.save_raw(root, data, ingest.extension_of(filename))
    dataset = describe(dataset_id, filename, len(data), df, detect.detect_roles(df), False)
    storage.write_metadata(root, dataset_id, dataset.model_dump(mode="json"))
    return dataset


@router.post("/sample", response_model=DatasetOut)
def load_sample(root: StorageRoot, sample_path: SamplePath) -> DatasetOut:
    """Return the shared sample with its roles already confirmed (FR-1.4)."""
    return shared_sample(root, sample_path)


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: str, root: StorageRoot) -> DatasetOut:
    """Metadata and roles for a stored dataset."""
    return DatasetOut.model_validate(storage.read_metadata(root, dataset_id))
