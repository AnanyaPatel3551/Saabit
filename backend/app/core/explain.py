""""How this was calculated", in plain words, for every answer card.

Written by code from the metric catalogue (metrics.py), the plan, the fix log and the card's
row count. No LLM is involved, and every number here comes from the data or the card.
"""

import csv
from datetime import date
from pathlib import Path

from app.core.evidence import EvidenceCard
from app.core.metrics import METRICS
from app.core.plan import Plan
from app.core.templates import day_text, format_count

MERGED_SHOWN = 4  # spellings listed per value, e.g. "RJ, Rajsthan, Rajshthan"
LABELS = {"state": "State", "city": "City", "category": "Category", "sku": "Product (SKU)",
          "fulfilment": "Fulfilment", "channel": "Sales channel"}


def merged_spellings(fixes_csv: Path, column: str) -> dict[str, list[str]]:
    """Clean value -> raw spellings merged into it (only those that differ beyond case)."""
    rule = f"{column}_normalised"
    merged: dict[str, list[str]] = {}
    if not fixes_csv.is_file():
        return merged
    with fixes_csv.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            before, after = row["before"].strip(), row["after"]
            if row["rule"] == rule and before.casefold() != after.casefold():
                merged.setdefault(after, []).append(before)
    return merged


def filter_lines(plan: Plan, fixes_csv: Path) -> list[str]:
    lines = []
    for f in plan.filters:
        label = LABELS.get(f.column, f.column)
        verb = "is not" if f.op == "not_in" else "is"
        lines.append(f"Only orders where {label} {verb} {', '.join(f.values)}.")
        merged = merged_spellings(fixes_csv, f.column)
        for value in f.values:
            spellings = merged.get(value, [])
            if spellings:
                shown = ", ".join(spellings[:MERGED_SHOWN])
                lines.append(f"{label} spellings were merged before counting: {shown} are "
                             f"counted as {value}.")
    return lines


def period_line(plan: Plan, first: date, last: date) -> str:
    if plan.date_range is not None:
        return (f"Period: {day_text(plan.date_range.start)} to "
                f"{day_text(plan.date_range.end)}.")
    return f"Period: every date in the file ({day_text(first)} to {day_text(last)})."


DIMENSION_WORDS = {"sku": "product code", "channel": "sales channel"}


def explanation(card: EvidenceCard, fixes_csv: Path, first: date, last: date) -> list[str]:
    """Plain sentences: what was measured, which orders, which dates, how many rows."""
    plan = Plan.model_validate(card.plan)
    metric = METRICS[plan.metric or "orders"]
    lines = [f"{metric.label}: {metric.definition}"]
    lines += filter_lines(plan, fixes_csv)
    if plan.group_by:
        lines.append("Split by " + " and ".join(DIMENSION_WORDS.get(d, d) for d in plan.group_by)
                     + ".")
    if plan.limit:
        order = "highest" if plan.sort is None or plan.sort.dir == "desc" else "lowest"
        lines.append(f"Showing the {order} {plan.limit}.")
    lines.append(period_line(plan, first, last))
    lines.append(f"Worked out from {format_count(card.row_count)} rows of your file, in two "
                 "separate ways that gave the same result.")
    return lines
