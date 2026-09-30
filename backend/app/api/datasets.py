"""Dataset routes: upload, load the sample, read metadata and roles."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, UploadFile

from app.api.errors import SampleUnavailable
from app.api.schemas import DatasetOut, RoleOut
from app.core import detect, ingest, storage

SAMPLE_PATH = Path(__file__).resolve().parents[3] / "data" / "sample" / "amazon_sale_report.csv"
SAMPLE_FILENAME = "amazon_sale_report.csv"
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

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def get_storage_root() -> Path:
    """Where dataset folders live. Overridden in tests."""
    return storage.storage_root()


def get_sample_path() -> Path:
    """Where the bundled sample lives. Overridden in tests."""
    return SAMPLE_PATH


StorageRoot = Annotated[Path, Depends(get_storage_root)]
SamplePath = Annotated[Path, Depends(get_sample_path)]


def store_dataset(
    root: Path, data: bytes, filename: str, df: pd.DataFrame,
    detection: detect.DetectionResult, confirmed: bool,
) -> DatasetOut:
    """Save the raw bytes, then metadata.json, and return what was stored."""
    dataset_id = storage.save_raw(root, data, ingest.extension_of(filename))
    dataset = DatasetOut(
        dataset_id=dataset_id,
        filename=filename,
        size_bytes=len(data),
        rows=len(df),
        created_at=datetime.now(UTC),
        columns=[str(c) for c in df.columns],
        roles=[RoleOut.model_validate(r) for r in detection.roles],
        roles_confirmed=confirmed,
        missing_required=detection.missing_required,
        unmapped_columns=detection.unmapped_columns,
    )
    storage.write_metadata(root, dataset_id, dataset.model_dump(mode="json"))
    return dataset


@router.post("", response_model=DatasetOut)
def upload_dataset(file: UploadFile, root: StorageRoot) -> DatasetOut:
    """Upload a CSV/XLSX; returns the dataset id and suggested roles (not yet confirmed)."""
    data = file.file.read(ingest.MAX_BYTES + 1)
    filename = file.filename or ""
    df = ingest.read_upload(data, filename)
    return store_dataset(root, data, filename, df, detect.detect_roles(df), confirmed=False)


@router.post("/sample", response_model=DatasetOut)
def load_sample(root: StorageRoot, sample_path: SamplePath) -> DatasetOut:
    """Load the bundled Amazon file with its roles already confirmed (FR-1.4)."""
    if not sample_path.is_file():
        raise SampleUnavailable()
    data = sample_path.read_bytes()
    df = ingest.read_bundled_file(sample_path)
    detection = detect.confirmed_roles(df, SAMPLE_ROLES)
    return store_dataset(root, data, SAMPLE_FILENAME, df, detection, confirmed=True)


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: str, root: StorageRoot) -> DatasetOut:
    """Metadata and roles for a stored dataset."""
    return DatasetOut.model_validate(storage.read_metadata(root, dataset_id))
