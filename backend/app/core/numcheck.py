"""Extract numbers from answer text and match them to computed results (FR-7.2).

A number in a sentence is allowed only if it is a result value, a difference or ratio of two
result values, or a number the user already supplied (in the question or the plan's dates).
Matching uses the precision the sentence used: "₹2.40 Cr" must equal a candidate rounded to
two decimals in crore, "14%" a candidate rounded to a whole percent.
"""

import re
from dataclasses import dataclass
from datetime import date
from itertools import permutations

from app.core.coverage import MonthCoverage
from app.core.plan import Plan
from app.core.templates import display_inr

CRORE = 10_000_000
LAKH = 100_000
NUMBER = re.compile(
    r"(?P<cur>₹|\bRs\.?|\bINR)?\s*"
    r"(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s*(?P<unit>%|per\s?cent\b|percentage\s+points?\b|pp\b|crores?\b|cr\b|lakhs?\b|lacs?\b))?",
    re.IGNORECASE,
)
PERCENT_UNITS = ("%", "per", "percentage", "pp")
TOLERANCE = 1e-9


@dataclass(frozen=True)
class Number:
    """One number found in text, scaled to plain units (₹, %, or a count)."""

    value: float
    kind: str  # "money", "percent" or "count"
    text: str
    mantissa: float  # as written, before crore/lakh scaling
    decimals: int
    scale: int

    def matches(self, candidate: float) -> bool:
        """True if the candidate, in this number's unit, rounds to what was written."""
        half_step = 0.5 * 10 ** -self.decimals
        return abs(abs(candidate) / self.scale - self.mantissa) <= half_step + TOLERANCE


def extract_numbers(text: str) -> list[Number]:
    """Every number in the text with its kind; date pieces like 2022-05-01 give 2022, 5, 1."""
    found = []
    for match in NUMBER.finditer(text):
        raw = match.group("num")
        unit = (match.group("unit") or "").lower()
        mantissa = float(raw.replace(",", ""))
        decimals = len(raw.split(".", 1)[1]) if "." in raw else 0
        scale = CRORE if unit.startswith("cr") else LAKH if unit.startswith(("lakh", "lac")) else 1
        if unit.startswith(PERCENT_UNITS):
            kind = "percent"
        elif match.group("cur") or scale > 1:
            kind = "money"
        else:
            kind = "count"
        found.append(Number(mantissa * scale, kind, match.group(0).strip(), mantissa,
                            decimals, scale))
    return found


def numeric_cells(rows: list[dict]) -> list[float]:
    return [float(v) for row in rows for k, v in row.items()
            if k in ("value", "orders") and isinstance(v, int | float)]


def key_numbers(rows: list[dict]) -> list[float]:
    """Numbers inside group keys ("2022-04", "SET389-KR") are part of the result."""
    return [n.mantissa for row in rows for k, v in row.items()
            if k not in ("value", "orders") and isinstance(v, str) for n in extract_numbers(v)]


def plan_numbers(plan: Plan) -> list[float]:
    numbers: list[float] = [plan.limit] if plan.limit else []
    if plan.date_range is not None:
        for day in (plan.date_range.start, plan.date_range.end):
            numbers += date_parts(day)
    return numbers


def date_parts(day: date) -> list[float]:
    return [day.year, day.month, day.day]


def coverage_numbers(partial: dict[str, MonthCoverage]) -> list[float]:
    """Days covered, days in the month and the dates named in each partial month's note."""
    return [n.mantissa for c in partial.values() for n in extract_numbers(c.sentence_note())]


def allowed_values(rows: list[dict], plan: Plan, question: str,
                   partial: dict[str, MonthCoverage] | None = None) -> list[float]:
    """Candidates a sentence may use: cells, differences, ratios, and user-given numbers."""
    cells = numeric_cells(rows)
    allowed = cells + key_numbers(rows) + plan_numbers(plan) + [len(rows)]
    allowed += coverage_numbers(partial or {})
    allowed += [n.mantissa for n in extract_numbers(question)]
    allowed += [n.value for n in extract_numbers(question)]
    for a, b in permutations(cells, 2):
        allowed.append(abs(a - b))  # differences, including percentage-point gaps
        if b:
            allowed.append(a / b * 100)  # "X is 45% of Y"
            allowed.append(abs(a / b - 1) * 100)  # "36% more often", "16% lower"
            allowed.append(a / b)  # "1.4 times"
    return allowed


def check(text: str, allowed: list[float]) -> tuple[bool, list[Number]]:
    """(ok, unmatched): ok only when every number in the text matches an allowed candidate."""
    unmatched = [n for n in extract_numbers(text)
                 if not any(n.matches(candidate) for candidate in allowed)]
    return not unmatched, unmatched


JUDGEMENT = re.compile(r"\b(low|lower|lowest|weak|weaker|weakest|worst|poor|slow|slump|high|higher|"
                       r"highest|best|peak|peaked|strong|stronger|strongest)\b", re.IGNORECASE)
COVERAGE_WORDS = re.compile(r"\b(days?|partial|missing|incomplete)\b", re.IGNORECASE)
SENTENCE = re.compile(r"[^.!?]+[.!?]?")


def month_names(cover: MonthCoverage) -> re.Pattern[str]:
    """'March', 'Mar' or '2022-03' as whole words."""
    names = {cover.first.strftime("%B"), cover.first.strftime("%b"), cover.month}
    return re.compile(r"\b(" + "|".join(sorted(names, key=len, reverse=True)) + r")\b",
                      re.IGNORECASE)


def misleads_on_partial(text: str, partial: dict[str, MonthCoverage]) -> bool:
    """True when a sentence names a partial month without saying it is partial, or calls it
    low or high: a one-day March is not a weak month, and a June missing a day did not
    really "fall" by the whole gap."""
    for sentence in SENTENCE.findall(text):
        for cover in partial.values():
            if not month_names(cover).search(sentence):
                continue
            if JUDGEMENT.search(sentence) or not COVERAGE_WORDS.search(sentence):
                return True
    return False


def off_style_amounts(text: str) -> list[str]:
    """Amounts not written exactly in the one sentence style (templates.display_inr): e.g.
    "₹1,22,24,770" where "₹1.22 Cr" was given, or "1.22 crore". The writer is told to copy
    amounts as given, so any other spelling means it reformatted one."""
    off = []
    for number in extract_numbers(text):
        if number.kind != "money":
            continue
        written = re.sub(r"\s+", " ", number.text).replace("₹ ", "₹")
        if written != display_inr(number.value):
            off.append(number.text)
    return off
