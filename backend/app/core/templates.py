"""Template sentences for every metric and grouping, so answers work with the LLM off (FR-7.3).

Templates use only result values, group keys and the plan's own dates and limit, so they
always pass the number checker.
"""

from datetime import date, datetime

from app.core.coverage import MonthCoverage
from app.core.metrics import METRICS
from app.core.plan import Plan

Partial = dict[str, MonthCoverage]

LISTED = 5  # groups named in a list sentence
TIME_DIMENSIONS = ("month", "week")


def indian_digits(whole: int) -> str:
    """1234567 -> 12,34,567 (last three digits, then pairs)."""
    digits = str(abs(whole))
    if len(digits) <= 3:
        grouped = digits
    else:
        head, tail = digits[:-3], digits[-3:]
        pairs = []
        while head:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        grouped = ",".join(pairs + [tail])
    return ("-" if whole < 0 else "") + grouped


def format_inr(value: float, short: bool = False) -> str:
    """₹2,39,53,534 in full, or ₹2.40 Cr / ₹69.19 lakh when short. Paise only below ₹1,000."""
    if short and abs(value) >= 10_000_000:
        return f"₹{value / 10_000_000:.2f} Cr"
    if short and abs(value) >= 100_000:
        return f"₹{value / 100_000:.2f} lakh"
    if abs(value) >= 1000 or float(value).is_integer():
        return f"₹{indian_digits(round(value))}"
    return f"₹{value:.2f}"


def format_pct(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}%"


def format_count(value: float) -> str:
    return indian_digits(round(value))


def format_value(metric: str, value: float | None) -> str:
    if value is None:
        return "not available"
    if metric in ("revenue", "aov"):
        return format_inr(value)
    if metric == "cancellation_rate":
        return format_pct(value)
    return format_count(value)


def day_text(day: date) -> str:
    return f"{day.day} {day.strftime('%b %Y')}"


def scope_text(plan: Plan) -> str:
    """ ' for Rajasthan, from 1 May 2022 to 31 May 2022' (empty when the whole file)."""
    parts = []
    for f in plan.filters:
        names = ", ".join(f.values)
        parts.append(f"excluding {names}" if f.op == "not_in" else f"for {names}")
    if plan.date_range is not None:
        parts.append(f"from {day_text(plan.date_range.start)} to {day_text(plan.date_range.end)}")
    return (" " + ", ".join(parts)) if parts else ""


def key_text(dimension: str, key: str | None) -> str:
    """Month and week keys read as dates; other keys as written."""
    if key is None:
        return "(blank)"
    if dimension == "month":
        return datetime.strptime(key, "%Y-%m").strftime("%b %Y")
    if dimension == "week":
        return "week of " + day_text(datetime.strptime(key, "%Y-%m-%d").date())
    return key


def group_label(plan: Plan, row: dict) -> str:
    return " / ".join(key_text(d, row.get(d)) for d in plan.group_by)


def noted_label(plan: Plan, row: dict, partial: Partial) -> str:
    """The group label, plus what a partial month holds: 'Mar 2022 (only 1 day of data, 31 Mar)'."""
    label = group_label(plan, row)
    cover = partial.get(row.get("month") or "") if "month" in plan.group_by else None
    return f"{label} ({cover.inline_note()})" if cover is not None else label


def range_note(plan: Plan, partial: Partial) -> str:
    """For a date range touching a partial month: ' Jun 2022 has 29 of 30 days of data (...).'"""
    if plan.date_range is None or "month" in plan.group_by:
        return ""
    first = plan.date_range.start.strftime("%Y-%m")
    last = plan.date_range.end.strftime("%Y-%m")
    notes = [f"{c.label} has {c.sentence_note()}" for m, c in sorted(partial.items())
             if first <= m <= last]
    return (" " + "; ".join(notes) + ".") if notes else ""


def single_value(plan: Plan, row: dict, scope: str) -> str:
    metric = plan.metric or ""
    value = format_value(metric, row.get("value"))
    orders = format_count(row["orders"])
    if metric == "orders":
        return f"There are {orders} orders{scope}."
    if metric == "revenue":
        return f"Revenue{scope} is {value}."
    if metric == "units":
        return f"Units sold{scope}: {value}."
    if metric == "aov":
        return f"Average order value{scope} is {value}."
    if metric == "cancelled_orders":
        return f"There are {value} cancelled orders{scope}."
    return f"The cancellation rate{scope} is {value} of {orders} orders."


def ranked(plan: Plan, rows: list[dict], scope: str, partial: Partial) -> str:
    """Sorted and limited by value: name the leader, or list the top N."""
    metric = plan.metric or ""
    label = METRICS[metric].label.lower()
    word = "highest" if plan.sort is None or plan.sort.dir == "desc" else "lowest"
    if len(rows) == 1:
        value = format_value(metric, rows[0].get("value"))
        return f"{noted_label(plan, rows[0], partial)} has the {word} {label}{scope} at {value}."
    listed = ", ".join(f"{noted_label(plan, r, partial)}: {format_value(metric, r.get('value'))}"
                       for r in rows)
    order = "Top" if word == "highest" else "Bottom"
    return f"{order} {len(rows)} by {label}{scope}: {listed}."


def listing(plan: Plan, rows: list[dict], scope: str, partial: Partial) -> str:
    """Groups in result order (time groupings are already chronological)."""
    metric = plan.metric or ""
    label = METRICS[metric].label
    by = " and ".join(plan.group_by)
    shown = ", ".join(f"{noted_label(plan, r, partial)} {format_value(metric, r.get('value'))}"
                      for r in rows[:LISTED])
    more = ", and others" if len(rows) > LISTED else ""
    return f"{label} by {by}{scope}: {shown}{more}."


def template_sentence(plan: Plan, rows: list[dict], partial: Partial | None = None) -> str:
    """A plain, always-correct answer sentence for any metric and grouping.

    partial (months the data covers only partly) never changes a value: a partial month is
    named with the days it holds, so it is not read as a weak or strong month.
    """
    partial = partial or {}
    scope = scope_text(plan)
    if not rows:
        return f"No orders match this question{scope}."
    note = range_note(plan, partial)
    if not plan.group_by:
        return single_value(plan, rows[0], scope) + note
    is_time = len(plan.group_by) == 1 and plan.group_by[0] in TIME_DIMENSIONS
    if not is_time and plan.sort is not None and plan.sort.by == "value" and plan.limit:
        return ranked(plan, rows, scope, partial) + note
    return listing(plan, rows, scope, partial) + note
