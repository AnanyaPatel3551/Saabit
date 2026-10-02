"""How many calendar days of each month the data covers (labels only, never values).

A month is partial when the data's date range misses its first or its last calendar day:
data from 31 Mar to 29 Jun 2022 gives March 1 of 31 days and June 29 of 30 days. This is
separate from cleaning's partial-month rule (FR-3.2), which feeds the recommendations'
backtest and the planner prompt and is left unchanged.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class MonthCoverage:
    """One month of the data: days covered out of days in the month."""

    month: str  # "2022-03"
    days: int
    of: int
    first: date  # first day with data in this month
    last: date  # last day with data in this month

    @property
    def partial(self) -> bool:
        return self.days < self.of

    @property
    def label(self) -> str:
        """'Mar 2022'."""
        return self.first.strftime("%b %Y")

    def short_note(self) -> str:
        """For chart tags and headlines: 'only 1 day' or '29 of 30 days'."""
        return "only 1 day" if self.days == 1 else f"{self.days} of {self.of} days"

    def inline_note(self) -> str:
        """Inside brackets after a label: 'only 1 day of data, 31 Mar'."""
        if self.days == 1:
            return f"only 1 day of data, {day_month(self.first)}"
        return f"{self.days} of {self.of} days, {missing_text(self)}"

    def sentence_note(self) -> str:
        """For sentences and caveats: what the data actually holds for this month."""
        if self.days == 1:
            return f"only 1 day of data ({day_month(self.first)})"
        return f"{self.days} of {self.of} days of data ({missing_text(self)})"


def day_month(day: date) -> str:
    """'31 Mar'."""
    return f"{day.day} {day.strftime('%b')}"


def missing_text(cover: MonthCoverage) -> str:
    """'missing 30 Jun', 'missing 1 Mar to 4 Mar', or both ends."""
    year, month = (int(p) for p in cover.month.split("-"))
    start, end = date(year, month, 1), date(year, month, cover.of)
    gaps = []
    if cover.first > start:
        gaps.append(span(start, cover.first - timedelta(days=1)))
    if cover.last < end:
        gaps.append(span(cover.last + timedelta(days=1), end))
    return "missing " + " and ".join(gaps)


def span(start: date, end: date) -> str:
    return day_month(start) if start == end else f"{day_month(start)} to {day_month(end)}"


def month_coverage(date_min: date | None, date_max: date | None) -> list[MonthCoverage]:
    """Every month from date_min to date_max with the days the range covers in it.

    Only the two edge months can be partial: the range is continuous between them.
    """
    if date_min is None or date_max is None or date_max < date_min:
        return []
    months = []
    cursor = date_min.replace(day=1)
    while cursor <= date_max:
        of = calendar.monthrange(cursor.year, cursor.month)[1]
        first = max(cursor, date_min)
        last = min(cursor.replace(day=of), date_max)
        months.append(MonthCoverage(cursor.strftime("%Y-%m"), (last - first).days + 1, of,
                                    first, last))
        cursor = cursor.replace(day=of) + timedelta(days=1)
    return months


def partial_coverage(date_min: date | None, date_max: date | None) -> dict[str, MonthCoverage]:
    """Only the partial months, keyed by '2022-03'."""
    return {c.month: c for c in month_coverage(date_min, date_max) if c.partial}
