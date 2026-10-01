"""Pydantic response models for the datasets API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.plan import Plan


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


class QuestionIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class PlanOut(BaseModel):
    """A planned question. Status ok plans are validated and snapped; the others explain."""

    plan: Plan
    caveats: list[str]
    cached: bool


class RunOut(BaseModel):
    """Answer to a plan.

    sentence is the checked LLM sentence (source "llm") or a template (source "template").
    When the engines disagree, sentence is null, source is "unverified" and note says
    "Could not verify" with both values.
    """

    verified: bool
    sentence: str | None
    source: str
    note: str | None
    card: CardOut


class RowsOut(BaseModel):
    """One page of the cleaned lines behind a card."""

    card_id: str
    page: int
    page_size: int
    total_rows: int
    pages: int
    rows: list[dict]


class OverviewOut(BaseModel):
    """The three workspace panels: data check, insight cards (E1-E5) and recommendations.

    status is "computing" until the background job finishes, then "ready" or "failed".
    rules lists every rule with its status (fired, not_fired, skipped) and reason.
    """

    status: str
    reason: str | None
    computed_at: str | None
    months: dict | None
    data_check: DataCheckOut
    insights: list[dict]
    recommendations: list[dict]
    rules: list[dict]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorOut(BaseModel):
    """Body of every error response."""

    error: ErrorDetail
