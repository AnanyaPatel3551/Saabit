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


class CapabilityItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    topic: str
    reason: str


class CapabilityOut(BaseModel):
    """What the file can and cannot answer, each with a reason (FR-3.5)."""

    model_config = ConfigDict(from_attributes=True)

    can_answer: list[CapabilityItemOut]
    cannot_answer: list[CapabilityItemOut]


class FixSummaryOut(BaseModel):
    """One cleaning rule and how many rows it touched; the full log is at /fixes."""

    rule: str
    rows_affected: int
    entries: int


class DataCheckOut(BaseModel):
    """Result of cleaning: row counts, what was fixed, and what the data can answer."""

    dataset_id: str
    rows_in: int
    rows_out: int
    partial_months: list[str]
    unknown_states: list[str]
    fixes: list[FixSummaryOut]
    capability: CapabilityOut


class ConfirmIn(BaseModel):
    """Final roles chosen by the user: role -> column name, or null to leave a role unused."""

    roles: dict[str, str | None]


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
    data_check: DataCheckOut | None = None


class CardOut(BaseModel):
    """An evidence card (FR-8.1). On a mismatch, sql_result and pandas_result are both set."""

    model_config = ConfigDict(from_attributes=True)

    card_id: str
    dataset_id: str
    plan: dict
    sql: str
    pandas_code: str
    verified: bool
    result: list[dict]
    caveats: list[str]
    row_count: int
    sql_result: list[dict] | None
    pandas_result: list[dict] | None
    mismatches: list[str]
    created_at: str


class RunOut(BaseModel):
    """Answer to a plan. sentence is written by the LLM in a later phase, so it is null now."""

    verified: bool
    sentence: str | None
    card: CardOut


class RowsOut(BaseModel):
    """One page of the cleaned lines behind a card."""

    card_id: str
    page: int
    page_size: int
    total_rows: int
    pages: int
    rows: list[dict]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorOut(BaseModel):
    """Body of every error response."""

    error: ErrorDetail
