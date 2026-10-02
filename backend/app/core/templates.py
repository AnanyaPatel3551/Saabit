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


def display_inr(value: float) -> str:
    """THE amount style for answer sentences (templates, writer input, number checker):
    ₹1.22 Cr from ₹1 crore, ₹96.50 lakh from ₹1 lakh, else Indian grouping (₹94,810; paise
    only below ₹1,000). Exact full-rupee values stay in charts, tables and evidence."""
    sign = "-" if value < 0 else ""
    amount = abs(value)
    if amount >= 10_000_000:
        return f"{sign}₹{amount / 10_000_000:.2f} Cr"
    if amount >= 100_000:
        return f"{sign}₹{amount / 100_000:.2f} lakh"
    if amount >= 1000 or float(amount).is_integer():
        return f"{sign}₹{indian_digits(round(amount))}"
    return f"{sign}₹{amount:.2f}"


def display_value(metric: str, value: float | None) -> str:
    """A result value as written in sentences: amounts via display_inr, rates with one
    decimal, counts with Indian grouping and no decimals."""
    if value is None:
        return "not available"
    if metric in ("revenue", "aov"):
        return display_inr(value)
    if metric == "cancellation_rate":
        return format_pct(value)
    return format_count(value)


def format_pct(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}%"


def format_count(value: float) -> str:
    return indian_digits(round(value))


def plural(count: float, noun: str, nouns: str | None = None) -> str:
    """'1 row', '1,24,093 rows', '53 state spellings' (Indian grouping, a real plural)."""
    word = noun if round(count) == 1 else (nouns or f"{noun}s")
    return f"{format_count(count)} {word}"


# What each cleaning rule did, in words (rules from core/clean.py). Used by answer caveats
# and the "Data fixes" insight card, and mirrored by the frontend's "What we cleaned up".
CLEAN_UP = {
    "state_normalised": ("state spelling", "fixed"),
    "city_normalised": ("city spelling", "merged"),
    "amount_cleaned": ("amount", "read as a plain number"),
    "amount_unparseable": ("unreadable amount", "left out"),
    "date_unparseable": ("unreadable date", "left out"),
    "duplicate_row": ("duplicate row", "removed"),
    "qty_not_integer": ("quantity that is not a whole number", "noted"),
}


def clean_up_text(rule: str, entries: int, rows: int) -> str:
    """'53 state spellings fixed in 1,24,093 rows'."""
    noun, verb = CLEAN_UP.get(rule, (rule.replace("_", " "), "changed"))
    nouns = IRREGULAR.get(noun)
    if rule in ("duplicate_row", "date_unparseable", "amount_unparseable", "qty_not_integer"):
        return f"{plural(rows, noun, nouns)} {verb}"
    return f"{plural(entries, noun, nouns)} {verb} in {plural(rows, 'row')}"


IRREGULAR = {"quantity that is not a whole number": "quantities that are not whole numbers"}


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
    value = display_value(metric, row.get("value"))
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
    """Sorted and limited by value, in the one ranking shape the writer is also shown:
    '{1st} leads with {v1}, followed by {2nd} ({v2}), {3rd} ({v3}) and {4th} ({v4}).'"""
    metric = plan.metric or ""
    label = METRICS[metric].label.lower()
    leads = "leads" if plan.sort is None or plan.sort.dir == "desc" else "is lowest"

    def shown(row: dict) -> str:
        return display_value(metric, row.get("value"))

    first = f"{noted_label(plan, rows[0], partial)} {leads} in {label}{scope} with {shown(rows[0])}"
    rest = [f"{noted_label(plan, r, partial)} ({shown(r)})" for r in rows[1:]]
    if not rest:
        return f"{first}."
    tail = rest[0] if len(rest) == 1 else ", ".join(rest[:-1]) + f" and {rest[-1]}"
    return f"{first}, followed by {tail}."


def listing(plan: Plan, rows: list[dict], scope: str, partial: Partial) -> str:
    """Groups in result order (time groupings are already chronological)."""
    metric = plan.metric or ""
    label = METRICS[metric].label
    by = " and ".join(plan.group_by)
    shown = ", ".join(f"{noted_label(plan, r, partial)} {display_value(metric, r.get('value'))}"
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
