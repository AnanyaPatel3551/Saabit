"""Compare the two engine results and attach caveats."""

import math
from dataclasses import dataclass, field

import pandas as pd

from app.core.coverage import MonthCoverage
from app.core.metrics import ABS_TOLERANCE, REL_TOLERANCE, SMALL_GROUP_ORDERS
from app.core.plan import Plan

COMPARED = ("value", "orders")
SMALL_GROUPS_LISTED = 5


@dataclass(frozen=True)
class Verification:
    """Outcome of comparing the SQL and pandas results (FR-6.1, FR-6.2)."""

    verified: bool
    rows: list[dict]  # the agreed result (the SQL rows); empty when not verified
    sql_rows: list[dict]
    pandas_rows: list[dict]
    mismatches: list[str] = field(default_factory=list)


def to_rows(df: pd.DataFrame, keys: list[str]) -> list[dict]:
    """Plain JSON-ready rows: keys as text, value as float (or None), orders as int."""
    rows = []
    for record in df.to_dict(orient="records"):
        row: dict = {k: None if pd.isna(record[k]) else str(record[k]) for k in keys}
        value = record["value"]
        row["value"] = None if value is None or pd.isna(value) else float(value)
        row["orders"] = int(record["orders"])
        rows.append(row)
    return rows


def close(a: float | None, b: float | None) -> bool:
    """FR-6.1: relative tolerance 1e-6 or absolute 0.01; two blanks are equal."""
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=REL_TOLERANCE, abs_tol=ABS_TOLERANCE)


def compare(sql_df: pd.DataFrame, pandas_df: pd.DataFrame, keys: list[str]) -> Verification:
    """Align the two results on their group keys and compare every value (FR-6.2)."""
    sql_rows, pandas_rows = to_rows(sql_df, keys), to_rows(pandas_df, keys)
    sql_by_key = {tuple(r[k] for k in keys): r for r in sql_rows}
    pandas_by_key = {tuple(r[k] for k in keys): r for r in pandas_rows}
    mismatches = []
    for key in sorted(set(sql_by_key) ^ set(pandas_by_key), key=str):
        side = "SQL" if key in sql_by_key else "pandas"
        mismatches.append(f"group {label(key)} appears only in the {side} result")
    for key in sorted(set(sql_by_key) & set(pandas_by_key), key=str):
        for name in COMPARED:
            a, b = sql_by_key[key][name], pandas_by_key[key][name]
            if not close(a, b):
                mismatches.append(f"{name} for {label(key)}: SQL {a} vs pandas {b}")
    verified = not mismatches
    return Verification(verified=verified, rows=sql_rows if verified else [],
                        sql_rows=sql_rows, pandas_rows=pandas_rows, mismatches=mismatches)


def label(key: tuple) -> str:
    return " / ".join(str(k) for k in key) if key else "(all)"


def months_in(plan: Plan, months: list[str]) -> list[str]:
    """Partial months worth a note: inside a chosen date range, or in a time breakdown.

    An all-time total (no date range, no month or week grouping) gets no note: it does
    not compare months, so a short month does not mislead.
    """
    by_time = any(d in ("month", "week") for d in plan.group_by)
    if plan.date_range is None:
        return list(months) if by_time else []
    first = plan.date_range.start.strftime("%Y-%m")
    last = plan.date_range.end.strftime("%Y-%m")
    return [m for m in months if first <= m <= last]


def caveats_for(
    plan: Plan, rows: list[dict], partial_months: list[str], cleaned_columns: dict[str, str],
    coverage: dict[str, MonthCoverage] | None = None,
) -> list[str]:
    """FR-6.3: partial months in range, cleaned columns used, and small groups.

    coverage adds months the data's date range cuts short at either edge, and says how many
    days each one holds; it only changes the wording, never a value.
    """
    notes = []
    coverage = coverage or {}
    for month in months_in(plan, sorted(set(partial_months) | set(coverage))):
        cover = coverage.get(month)
        if cover is not None:
            notes.append(f"{cover.label} is a partial month: {cover.sentence_note()}, so it is "
                         "not comparable to full months.")
        else:
            notes.append(f"{month} is a partial month in this data, so it is not comparable "
                         "to full months.")
    used = list(dict.fromkeys([f.column for f in plan.filters] + list(plan.group_by)))
    for column in used:
        if column in cleaned_columns:
            notes.append(f"{column.capitalize()} values were cleaned before this ran: "
                         f"{cleaned_columns[column]} (see What we cleaned up).")
    small = [r for r in rows if r["orders"] < SMALL_GROUP_ORDERS]
    if small:
        listed = ", ".join(f"{label(tuple(r[k] for k in plan.group_by))} ({r['orders']})"
                           for r in small[:SMALL_GROUPS_LISTED])
        extra = len(small) - SMALL_GROUPS_LISTED
        more = f" and {extra} more" if extra > 0 else ""
        notes.append(f"Based on fewer than {SMALL_GROUP_ORDERS} orders: {listed}{more}.")
    return notes
