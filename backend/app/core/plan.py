"""Pydantic plan schema + validation + value snapping."""

import difflib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.metrics import DIMENSIONS, MAX_GROUP_BY, MAX_ROWS, METRICS
from app.core.states import fold, state_lookup

DimensionName = Literal["month", "week", "state", "city", "category", "sku", "fulfilment",
                        "channel"]
FilterColumn = Literal["state", "city", "category", "sku", "fulfilment", "channel"]
CLOSEST_OPTIONS = 5


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Filter(StrictModel):
    column: FilterColumn
    op: Literal["eq", "in", "not_in"] = "eq"
    values: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def eq_has_one_value(self) -> "Filter":
        if self.op == "eq" and len(self.values) != 1:
            raise ValueError("op 'eq' takes exactly one value; use 'in' for several")
        return self


class DateRange(StrictModel):
    start: date
    end: date

    @model_validator(mode="after")
    def start_before_end(self) -> "DateRange":
        if self.end < self.start:
            raise ValueError("date_range end is before start")
        return self


class Sort(StrictModel):
    by: Literal["value", "key"] = "value"
    dir: Literal["asc", "desc"] = "desc"


class Clarification(StrictModel):
    question: str
    options: list[str]


class Plan(StrictModel):
    """The structured question (PRD Step 4). Only status 'ok' plans can run."""

    status: Literal["ok", "needs_clarification", "unsupported"] = "ok"
    metric: str | None = None
    group_by: list[DimensionName] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    date_range: DateRange | None = None
    sort: Sort | None = None
    limit: int | None = Field(default=None, ge=1)
    clarification: Clarification | None = None
    unsupported_reason: str | None = None


class PlanError(Exception):
    """A plan that cannot run on this dataset; the message says why in plain words."""

    code = "invalid_plan"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class UnknownFilterValue(PlanError):
    code = "unknown_filter_value"

    def __init__(self, message: str, options: list[str]) -> None:
        self.options = options
        super().__init__(message)


@dataclass(frozen=True)
class DatasetInfo:
    """What validation needs to know about a cleaned dataset."""

    roles: frozenset[str]
    date_min: date
    date_max: date
    values: Callable[[str], list[str]]  # distinct non-blank values of a canonical column


def validate_plan(plan: Plan, dataset: DatasetInfo) -> tuple[Plan, list[str]]:
    """Check the plan against the dataset; return the (possibly clipped) plan and caveats."""
    if plan.status != "ok":
        raise PlanError(f"This plan cannot run: its status is '{plan.status}'.")
    if plan.metric not in METRICS:
        raise PlanError(f"Unknown metric '{plan.metric}'. Choose one of: {', '.join(METRICS)}.")
    metric = METRICS[plan.metric]
    missing = [r for r in metric.required_roles if r not in dataset.roles]
    if missing:
        raise PlanError(f"{metric.label} needs a {', '.join(missing)} column, which this "
                        "dataset does not have.")
    check_dimensions(plan, dataset)
    if plan.limit is not None and plan.limit > MAX_ROWS:
        raise PlanError(f"limit is {plan.limit}; the most a result can have is {MAX_ROWS} rows.")
    caveats = [] if "status" in dataset.roles else [
        "This file has no order status column, so cancelled orders cannot be excluded."
    ]
    if plan.date_range is None:
        return plan, caveats
    clipped, note = clip_dates(plan.date_range, dataset)
    return plan.model_copy(update={"date_range": clipped}), caveats + ([note] if note else [])


def check_dimensions(plan: Plan, dataset: DatasetInfo) -> None:
    """Grouping and filter columns must be confirmed roles; at most MAX_GROUP_BY groupings."""
    if len(plan.group_by) > MAX_GROUP_BY:
        raise PlanError(f"Group by at most {MAX_GROUP_BY} columns at once.")
    if len(set(plan.group_by)) != len(plan.group_by):
        raise PlanError("The same column appears twice in group_by.")
    used = [(name, "group by") for name in plan.group_by]
    used += [(f.column, "filter on") for f in plan.filters]
    for name, action in used:
        if DIMENSIONS[name].role not in dataset.roles:
            raise PlanError(f"Cannot {action} {name}: this dataset has no {name} column.")


def clip_dates(requested: DateRange, dataset: DatasetInfo) -> tuple[DateRange, str | None]:
    """Clip the range to the data; a range with no overlap at all is an error."""
    if requested.end < dataset.date_min or requested.start > dataset.date_max:
        raise PlanError(
            f"There is no data between {requested.start} and {requested.end}. "
            f"This dataset covers {dataset.date_min} to {dataset.date_max}."
        )
    start = max(requested.start, dataset.date_min)
    end = min(requested.end, dataset.date_max)
    if (start, end) == (requested.start, requested.end):
        return requested, None
    note = (f"The date range {requested.start} to {requested.end} was clipped to "
            f"{start} to {end}, the dates this dataset covers.")
    return DateRange(start=start, end=end), note


def snap_values(plan: Plan, dataset: DatasetInfo) -> Plan:
    """Replace each filter value with the real value it matches, ignoring case (FR-4.4).

    State filters also accept known variants such as RJ. An unknown value raises
    UnknownFilterValue listing the closest real values.
    """
    real_values: dict[str, list[str]] = {}
    for f in plan.filters:
        if f.column not in real_values:
            real_values[f.column] = dataset.values(f.column)
    filters = [f.model_copy(update={"values": [snap(v, f.column, real_values[f.column])
                                               for v in f.values]})
               for f in plan.filters]
    return plan.model_copy(update={"filters": filters})


def snap(value: str, column: str, real: list[str]) -> str:
    by_key = {fold(v): v for v in real}
    key = fold(value)
    if key in by_key:
        return by_key[key]
    if column == "state":
        canonical = state_lookup().get(key)
        if canonical is not None and fold(canonical) in by_key:
            return by_key[fold(canonical)]
    options = difflib.get_close_matches(value, real, n=CLOSEST_OPTIONS, cutoff=0.4)
    if not options:
        options = difflib.get_close_matches(key, [fold(v) for v in real], n=CLOSEST_OPTIONS,
                                            cutoff=0.4)
        options = [by_key[o] for o in options]
    options = options or sorted(real)[:CLOSEST_OPTIONS]
    raise UnknownFilterValue(
        f"'{value}' is not a {column} in this dataset. Closest matches: {', '.join(options)}.",
        options,
    )
