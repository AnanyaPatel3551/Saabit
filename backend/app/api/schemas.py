"""Pydantic response models for the datasets API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RoleOut(BaseModel):
    """One role and the column suggested (or confirmed) for it."""

    model_config = ConfigDict(from_attributes=True)

    role: str
    column: str | None
    confidence: float
    reasons: list[str]
    samples: list[str]


class DatasetOut(BaseModel):
    """A stored dataset: its metadata plus the role for every column type."""

    dataset_id: str
    filename: str
    size_bytes: int
    rows: int
    created_at: datetime
    columns: list[str]
    roles: list[RoleOut]
    roles_confirmed: bool
    missing_required: list[str]
    unmapped_columns: list[str]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorOut(BaseModel):
    """Body of every error response."""

    error: ErrorDetail
