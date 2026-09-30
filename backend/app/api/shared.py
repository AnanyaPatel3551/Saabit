"""Helpers used by more than one route module."""

from datetime import UTC, datetime

from app.api.schemas import DatasetOut, RoleOut
from app.core import detect


def describe(
    dataset_id: str, filename: str, size_bytes: int, rows: int, columns: list[str],
    detection: detect.DetectionResult, confirmed: bool,
) -> DatasetOut:
    """Build the metadata record stored in metadata.json and returned by the API."""
    return DatasetOut(
        dataset_id=dataset_id,
        filename=filename,
        size_bytes=size_bytes,
        rows=rows,
        created_at=datetime.now(UTC),
        columns=columns,
        roles=[RoleOut.model_validate(r) for r in detection.roles],
        roles_confirmed=confirmed,
        missing_required=detection.missing_required,
        unmapped_columns=detection.unmapped_columns,
    )
