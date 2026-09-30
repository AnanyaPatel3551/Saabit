"""Dataset routes: upload, load the sample, read metadata and roles."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile

from app.api.sample import (
    SAMPLE_PATH,
    SAMPLE_ROLES,
    get_sample_cache_dir,
    get_sample_path,
    read_cached_sample,
    shared_sample,
)
from app.api.schemas import DatasetOut
from app.api.shared import describe
from app.core import detect, ingest, storage

__all__ = ["SAMPLE_PATH", "SAMPLE_ROLES", "get_sample_path", "get_storage_root", "router"]

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def get_storage_root() -> Path:
    """Where dataset folders live. Overridden in tests."""
    return storage.storage_root()


StorageRoot = Annotated[Path, Depends(get_storage_root)]
SamplePath = Annotated[Path, Depends(get_sample_path)]
SampleCache = Annotated[Path, Depends(get_sample_cache_dir)]


@router.post("", response_model=DatasetOut)
def upload_dataset(file: UploadFile, root: StorageRoot) -> DatasetOut:
    """Upload a CSV/XLSX; returns the dataset id and suggested roles (not yet confirmed).

    The upload is streamed to disk in chunks and inspected from there; a rejected file
    leaves nothing behind.
    """
    filename = file.filename or ""
    extension = ingest.extension_of(filename)
    dataset_id, folder = storage.new_dataset(root)
    try:
        raw = storage.raw_path(folder, extension)
        size = ingest.save_upload(file.file, raw)
        table = ingest.read_table(raw, filename, folder)
        detection = detect.detect_roles(table.head, table.rows)
        dataset = describe(
            dataset_id, filename, size, table.rows, table.columns, detection, confirmed=False
        )
        storage.write_metadata(root, dataset_id, dataset.model_dump(mode="json"))
    except BaseException:
        storage.delete_dataset(root, dataset_id)
        raise
    return dataset


@router.post("/sample", response_model=DatasetOut)
def load_sample(sample_path: SamplePath, cache_dir: SampleCache) -> DatasetOut:
    """Return the shared sample with its roles already confirmed (FR-1.4)."""
    return shared_sample(sample_path, cache_dir)


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: str, root: StorageRoot, cache_dir: SampleCache) -> DatasetOut:
    """Metadata and roles for a stored dataset, including the shared sample."""
    sample = read_cached_sample(cache_dir)
    if sample is not None and sample.dataset_id == dataset_id:
        return sample
    return DatasetOut.model_validate(storage.read_metadata(root, dataset_id))
