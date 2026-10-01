"""Score columns to detect their roles."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache, cached_property

import pandas as pd

from app.core.states import state_lookup

ROLES = (
    "order_id", "order_date", "amount", "status", "state", "city",
    "category", "sku", "fulfilment", "qty", "channel",
)
REQUIRED_ROLES = ("order_id", "order_date", "amount")

SUGGEST_THRESHOLD = 0.8
HEADER_EXACT = 0.5
HEADER_PARTIAL = 0.3
VALUES_PASS = 0.5
DETECTION_ROWS = 50_000
# Role values (ids, dates, amounts, states, SKUs) are short; long free text never fits a role,
# so profiling reads only this many characters of each value to bound memory.
MAX_VALUE_CHARS = 100
SAMPLE_COUNT = 3
CONFIRMED_SAMPLE_ROWS = 1000

SYNONYMS: dict[str, tuple[str, ...]] = {
    "order_id": ("order id", "orderid", "order no", "order number", "order ref", "invoice id",
                 "invoice no", "invoice number"),
    "order_date": ("date", "order date", "created at", "purchase date", "order time",
                   "invoice date", "transaction date"),
    "amount": ("amount", "total", "order total", "sales", "revenue", "price", "total price",
               "net amount", "gross amount", "item total", "subtotal"),
    "status": ("status", "order status", "delivery status", "shipment status"),
    "state": ("state", "ship state", "shipping state", "province", "shipping province", "region",
              "billing state", "delivery state"),
    "city": ("city", "ship city", "shipping city", "town", "billing city", "delivery city"),
    "category": ("category", "product category", "item category", "department"),
    "sku": ("sku", "seller sku", "product sku", "item sku", "variant sku", "product code",
            "item code"),
    "fulfilment": ("fulfilment", "fulfillment", "fulfilment type", "fulfillment type",
                   "shipped by"),
    "qty": ("qty", "quantity", "units", "quantity ordered", "qty ordered", "item quantity"),
    "channel": ("channel", "sales channel", "source", "marketplace", "platform", "order source"),
}

# Words too generic to count as a partial header match on their own.
STOP_WORDS = frozenset({
    "ship", "shipping", "order", "id", "no", "number", "by", "at", "of", "the", "line",
    "lineitem", "item", "sales", "type", "product", "total", "delivery", "billing", "invoice",
})

# Header words that mean the column is about something else, even if the rest matches:
# a courier's tracking status is not the order's outcome.
NOT_THIS_ROLE: dict[str, frozenset[str]] = {
    "status": frozenset({"courier", "carrier", "payment", "refund"}),
}

STATUS_WORDS = ("cancel", "ship", "deliver", "return", "pending", "paid", "refund", "fulfil",
                "void", "complete")
# One pattern, three accepted shapes: 04-30-22 / 2022-04-30 10:00, 30 Apr 2022, Apr 30, 2022.
DATE_PATTERN = (
    r"(?:\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}(?:[ T].*)?$)"
    r"|(?:\d{1,2}[ -][A-Za-z]{3,9}[ -,]+\d{2,4})"
    r"|(?:[A-Za-z]{3,9} \d{1,2},? \d{4})"
)
# Patterns stay within what Arrow's RE2 engine supports (no lookaheads, no flags), so pandas
# runs them natively instead of falling back to a slow per-value Python loop.
SKU_CHARS = r"^[A-Za-z0-9._/-]+$"
SKU_HAS_LETTER = r"[A-Za-z]"
SKU_HAS_DIGIT_OR_SEPARATOR = r"[\d._/-]"
NUMBER_NOISE = r"[₹,\s]|[Rr][Ss]\.?|INR|inr"


@dataclass(frozen=True)
class RoleSuggestion:
    """Best column for one role. column is None when confidence is below the threshold."""

    role: str
    column: str | None
    confidence: float
    reasons: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DetectionResult:
    """Suggestions for every role, plus what is missing or unused."""

    roles: list[RoleSuggestion]
    missing_required: list[str]
    unmapped_columns: list[str]


@dataclass(frozen=True)
class ColumnProfile:
    """Facts about one column, computed once and shared by every role check.

    Derived numbers are cached as plain ints and floats; no extra copies of the
    column are kept, so memory stays at one column of text plus one of numbers.
    """

    name: str
    values: pd.Series
    numbers: pd.Series

    @property
    def count(self) -> int:
        return len(self.values)

    @cached_property
    def distinct(self) -> int:
        return int(self.values.nunique())

    def share(self, mask: pd.Series) -> float:
        return float(mask.mean()) if self.count else 0.0

    @cached_property
    def numeric(self) -> float:
        return self.share(self.numbers.notna())

    def numeric_share(self) -> float:
        return self.numeric

    @cached_property
    def state_share(self) -> float:
        return self.share(self.values.str.lower().isin(state_names()))

    def uniques(self, limit: int) -> list[str] | None:
        """The distinct values if there are at most `limit` of them, else None."""
        return None if self.distinct > limit else [str(v) for v in self.values.unique()]


@dataclass(frozen=True)
class Candidate:
    role: str
    column: str
    confidence: float
    reasons: list[str]


@cache
def state_names() -> frozenset[str]:
    """Lower-case canonical state and UT names plus their known variants."""
    return frozenset(state_lookup())


def normalise_header(header: str) -> str:
    """Lower-case, turn - _ . / into spaces, collapse repeated spaces."""
    return " ".join(re.sub(r"[-_./]", " ", header.lower()).split())


def content_words(text: str) -> set[str]:
    return set(text.split()) - STOP_WORDS


def header_score(header: str, role: str) -> tuple[float, str]:
    """0.5 for an exact synonym, 0.3 if a meaningful word is shared, else 0."""
    normalised = normalise_header(header)
    excluded = NOT_THIS_ROLE.get(role, frozenset()) & set(normalised.split())
    if excluded:
        return 0.0, f"header '{header}' names a {sorted(excluded)[0]}, not this role"
    if normalised in SYNONYMS[role]:
        return HEADER_EXACT, f"header '{header}' matches '{normalised}'"
    words = content_words(normalised)
    for synonym in SYNONYMS[role]:
        shared = words & content_words(synonym)
        if shared:
            return HEADER_PARTIAL, f"header '{header}' contains '{sorted(shared)[0]}'"
    return 0.0, ""


def profile_column(name: str, series: pd.Series) -> ColumnProfile:
    """Non-blank values from the first DETECTION_ROWS rows, and their numeric reading."""
    values = series.head(DETECTION_ROWS).dropna()
    if not isinstance(values.dtype, pd.StringDtype):
        values = values.astype("string[pyarrow]")
    values = values.str.slice(0, MAX_VALUE_CHARS).str.strip()
    values = values[values != ""].reset_index(drop=True)
    numbers = pd.to_numeric(values.str.replace(NUMBER_NOISE, "", regex=True), errors="coerce")
    return ColumnProfile(name=name, values=values, numbers=numbers)


def pct(share: float) -> str:
    return f"{share:.0%}"


def check_order_id(p: ColumnProfile) -> tuple[bool, str]:
    ratio = p.distinct / p.count if p.count else 0.0
    return ratio >= 0.5, f"{pct(ratio)} of values are distinct (needs 50%)"


def check_order_date(p: ColumnProfile) -> tuple[bool, str]:
    looks_like_date = p.values.str.match(DATE_PATTERN)
    if p.share(looks_like_date) >= 0.95:
        parsed = pd.to_datetime(p.values, errors="coerce", format="mixed")
        looks_like_date &= parsed.notna()
    share = p.share(looks_like_date)
    return share >= 0.95, f"{pct(share)} of values parse as dates (needs 95%)"


def check_amount(p: ColumnProfile) -> tuple[bool, str]:
    share = p.numeric_share()
    return share >= 0.95, f"{pct(share)} of values are numeric (needs 95%)"


def check_qty(p: ColumnProfile) -> tuple[bool, str]:
    small_whole = p.numbers.notna() & (p.numbers % 1 == 0) & p.numbers.between(0, 1000)
    share = p.share(small_whole)
    return share >= 0.95, f"{pct(share)} of values are whole numbers from 0 to 1000 (needs 95%)"


def check_status(p: ColumnProfile) -> tuple[bool, str]:
    uniques = p.uniques(30)
    if uniques is None:
        return False, f"{p.distinct} distinct values (max 30)"
    lowered = [value.lower() for value in uniques]
    words = [w for w in STATUS_WORDS if any(w in value for value in lowered)]
    shown = ", ".join(words) if words else "none"
    return bool(words), f"{p.distinct} distinct values (max 30); status words found: {shown}"


def check_state(p: ColumnProfile) -> tuple[bool, str]:
    share = p.state_share
    return share >= 0.6, f"{pct(share)} of values are known Indian states (needs 60%)"


def check_city(p: ColumnProfile) -> tuple[bool, str]:
    text, states = 1 - p.numeric_share(), p.state_share
    passed = p.count > 0 and text >= 0.95 and states < 0.6
    return passed, f"{pct(text)} text values, {pct(states)} are state names (needs under 60%)"


def check_category(p: ColumnProfile) -> tuple[bool, str]:
    text = 1 - p.numeric_share()
    passed = p.count > 0 and text >= 0.95 and p.distinct <= 100
    return passed, f"{pct(text)} text values, {p.distinct} distinct (max 100)"


def check_sku(p: ColumnProfile) -> tuple[bool, str]:
    code_like = (
        p.values.str.match(SKU_CHARS)
        & p.values.str.contains(SKU_HAS_LETTER)
        & p.values.str.contains(SKU_HAS_DIGIT_OR_SEPARATOR)
    )
    share = p.share(code_like)
    return share >= 0.8, f"{pct(share)} of values look like product codes (needs 80%)"


def few_text_values(p: ColumnProfile, limit: int) -> tuple[bool, str]:
    text = 1 - p.numeric_share()
    passed = p.count > 0 and text >= 0.95 and p.distinct <= limit
    return passed, f"{pct(text)} text values, {p.distinct} distinct (max {limit})"


VALUE_CHECKS: dict[str, Callable[[ColumnProfile], tuple[bool, str]]] = {
    "order_id": check_order_id,
    "order_date": check_order_date,
    "amount": check_amount,
    "status": check_status,
    "state": check_state,
    "city": check_city,
    "category": check_category,
    "sku": check_sku,
    "fulfilment": lambda p: few_text_values(p, 10),
    "qty": check_qty,
    "channel": lambda p: few_text_values(p, 20),
}


def score(profile: ColumnProfile, role: str, scope: str = "") -> Candidate:
    """Confidence = header score + value score, with the reasons for each part.

    scope, when set, says which rows the value check looked at.
    """
    head, head_reason = header_score(profile.name, role)
    if profile.count == 0:
        passed, value_reason = False, "column is empty"
    else:
        passed, value_reason = VALUE_CHECKS[role](profile)
    confidence = round(head + (VALUES_PASS if passed else 0.0), 2)
    value_reason = ("values" if passed else "values fail") + f"{scope}: {value_reason}"
    reasons = [r for r in (head_reason, value_reason) if r]
    return Candidate(role=role, column=profile.name, confidence=confidence, reasons=reasons)


def assign(candidates: list[Candidate]) -> dict[str, Candidate]:
    """Highest confidence first; each role and each column is used at most once."""
    ranked = sorted(candidates, key=lambda c: (-c.confidence, ROLES.index(c.role)))
    chosen: dict[str, Candidate] = {}
    used_columns: set[str] = set()
    for c in ranked:
        free = c.role not in chosen and c.column not in used_columns
        if c.confidence >= SUGGEST_THRESHOLD and free:
            chosen[c.role] = c
            used_columns.add(c.column)
    return chosen


def samples(profile: ColumnProfile) -> list[str]:
    return [str(v) for v in profile.values.drop_duplicates().head(SAMPLE_COUNT)]


def best_unassigned(role: str, candidates: list[Candidate]) -> Candidate | None:
    for_role = [c for c in candidates if c.role == role]
    return max(for_role, key=lambda c: c.confidence, default=None)


def suggestion_for(
    role: str, chosen: dict[str, Candidate], candidates: list[Candidate],
    sample_values: dict[str, list[str]],
) -> RoleSuggestion:
    if role in chosen:
        c = chosen[role]
        return RoleSuggestion(role, c.column, c.confidence, c.reasons, sample_values[c.column])
    best = best_unassigned(role, candidates)
    if best is None or best.confidence == 0:
        return RoleSuggestion(role, None, 0.0, ["no column looks like this role"], [])
    note = f"best candidate '{best.column}' scored {best.confidence:.2f}, below {SUGGEST_THRESHOLD}"
    if best.confidence >= SUGGEST_THRESHOLD:
        note = f"best candidate '{best.column}' was already used for another role"
    reasons = [note, *best.reasons]
    return RoleSuggestion(role, None, best.confidence, reasons, sample_values[best.column])


def check_scope(checked: int, total: int) -> str:
    """Note for the reasons when the value checks saw only part of the file."""
    return f" (first {checked:,} of {total:,} rows)" if total > checked else ""


def detect_roles(df: pd.DataFrame, total_rows: int | None = None) -> DetectionResult:
    """Suggest a column for each role (FR-2.1, FR-2.2); blank when confidence is under 0.8.

    Value checks use at most the first DETECTION_ROWS rows of df. total_rows is the row
    count of the whole file, so the reasons can say how much of it was checked.
    """
    checked = min(len(df), DETECTION_ROWS)
    scope = check_scope(checked, max(total_rows or 0, len(df)))
    candidates: list[Candidate] = []
    sample_values: dict[str, list[str]] = {}
    for name in df.columns:
        # One column at a time: its profile is dropped once scored, keeping memory flat.
        profile = profile_column(str(name), df[name])
        candidates += [score(profile, role, scope) for role in ROLES]
        sample_values[str(name)] = samples(profile)
    chosen = assign(candidates)
    roles = [suggestion_for(role, chosen, candidates, sample_values) for role in ROLES]
    used = {c.column for c in chosen.values()}
    return DetectionResult(
        roles=roles,
        missing_required=[r for r in REQUIRED_ROLES if r not in chosen],
        unmapped_columns=[name for name in sample_values if name not in used],
    )


def confirmed_roles(
    df: pd.DataFrame, mapping: dict[str, str], columns: list[str] | None = None
) -> DetectionResult:
    """Roles fixed in advance (the bundled sample): confidence 1.0, with sample values.

    df needs only the mapped columns; columns lists every column in the file.
    """
    all_columns = columns if columns is not None else [str(c) for c in df.columns]
    # No value checks are needed, only three example values, so a small head is enough.
    head = df.head(CONFIRMED_SAMPLE_ROWS)
    profiles = {role: profile_column(column, head[column]) for role, column in mapping.items()}
    roles = [
        RoleSuggestion(role, mapping[role], 1.0, ["pre-confirmed for the bundled sample"],
                       samples(profiles[role]))
        if role in mapping else RoleSuggestion(role, None, 0.0, ["not used by the sample"], [])
        for role in ROLES
    ]
    return DetectionResult(
        roles=roles,
        missing_required=[r for r in REQUIRED_ROLES if r not in mapping],
        unmapped_columns=[c for c in all_columns if c not in set(mapping.values())],
    )
