"""Per-dataset folders on local disk: the raw upload and metadata.json."""

import json
import os
import re
import secrets
import shutil
from pathlib import Path
from typing import Any

STORAGE_ENV = "SAABIT_STORAGE_DIR"
PLAN_CACHE_ENV = "SAABIT_PLAN_CACHE"
DEFAULT_STORAGE_DIR = "storage"
ID_PATTERN = re.compile(r"^[0-9a-f]{12}$")
METADATA_FILE = "metadata.json"
RAW_STEM = "raw"


class DatasetNotFound(Exception):
    """No dataset exists for the given id (or the id is malformed)."""

    code = "dataset_not_found"

    def __init__(self, dataset_id: str) -> None:
        self.message = f"No dataset with id '{dataset_id}'. It may have expired."
        super().__init__(self.message)


def storage_root() -> Path:
    """Folder that holds one sub-folder per dataset (SAABIT_STORAGE_DIR, default ./storage)."""
    return Path(os.environ.get(STORAGE_ENV) or DEFAULT_STORAGE_DIR)


def plan_cache_dir() -> Path:
    """Where planned questions are kept on disk (SAABIT_PLAN_CACHE, default storage/plan_cache)."""
    return Path(os.environ.get(PLAN_CACHE_ENV) or storage_root() / "plan_cache")


def new_dataset_id() -> str:
    """Short random id: 12 hex characters (48 random bits)."""
    return secrets.token_hex(6)


def dataset_dir(root: Path, dataset_id: str) -> Path:
    """Folder for one dataset. The id is validated so it can never point outside root."""
    if not ID_PATTERN.fullmatch(dataset_id):
        raise DatasetNotFound(dataset_id)
    return root / dataset_id


def new_dataset(root: Path) -> tuple[str, Path]:
    """Create an empty folder for a new upload; return its random id and path."""
    dataset_id = new_dataset_id()
    folder = dataset_dir(root, dataset_id)
    folder.mkdir(parents=True, exist_ok=False)
    return dataset_id, folder


def raw_path(folder: Path, extension: str) -> Path:
    """Where the upload is kept byte-for-byte: raw.csv or raw.xlsx, never the user's name."""
    return folder / f"{RAW_STEM}{extension}"


def delete_dataset(root: Path, dataset_id: str) -> None:
    """Remove a dataset folder and everything in it: raw file, cleaned data, evidence cards
    (a rejected upload, or "Delete my data now")."""
    shutil.rmtree(dataset_dir(root, dataset_id), ignore_errors=True)


def create_dataset_dir(root: Path, dataset_id: str) -> Path:
    """Create (or reuse) the folder for a dataset with a known id, such as the shared sample."""
    folder = dataset_dir(root, dataset_id)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write_metadata(root: Path, dataset_id: str, metadata: dict[str, Any]) -> None:
    """Write metadata.json for an existing dataset."""
    path = dataset_dir(root, dataset_id) / METADATA_FILE
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def read_metadata(root: Path, dataset_id: str) -> dict[str, Any]:
    """Read metadata.json, or raise DatasetNotFound."""
    path = dataset_dir(root, dataset_id) / METADATA_FILE
    if not path.is_file():
        raise DatasetNotFound(dataset_id)
    return json.loads(path.read_text(encoding="utf-8"))
