"""Score columns to detect their roles."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import pandas as pd

ROLES = (
    "order_id", "order_date", "amount", "status", "state", "city",
    "category", "sku", "fulfilment", "qty", "channel",
)
REQUIRED_ROLES = ("order_id", "order_date", "amount")

SUGGEST_THRESHOLD = 0.8
HEADER_EXACT = 0.5
HEADER_PARTIAL = 0.3
VALUES_PASS = 0.5
PROFILE_ROWS = 5000
SAMPLE_COUNT = 3

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

STATUS_WORDS = ("cancel", "ship", "deliver", "return", "pending", "paid", "refund", "fulfil",
                "void", "complete")
DATE_PATTERNS = (
    re.compile(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}([ T].*)?$"),
    re.compile(r"^\d{1,2}[ -][A-Za-z]{3,9}[ -,]+\d{2,4}"),
    re.compile(r"^[A-Za-z]{3,9} \d{1,2},? \d{4}"),
)
SKU_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*[\d._/-])[A-Za-z0-9._/-]+$")
NUMBER_NOISE = re.compile(r"[₹,\s]|Rs\.?|INR", re.IGNORECASE)
STATES_FILE = Path(__file__).resolve().parents[1] / "data" / "states.json"


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
    """Facts about one column, computed once and shared by every role check."""

    name: str
    values: pd.Series
    numbers: pd.Series

    @property
    def count(self) -> int:
        return len(self.values)

    @property
    def distinct(self) -> int:
        return int(self.values.nunique())

    def share(self, mask: pd.Series) -> float:
        return float(mask.mean()) if self.count else 0.0

    def numeric_share(self) -> float:
        return self.share(self.numbers.notna())


@dataclass(frozen=True)
class Candidate:
    role: str
    column: str
    confidence: float
    reasons: list[str]


@cache
def state_names() -> frozenset[str]:
    """Lower-case canonical state and UT names plus their known variants."""
    data = json.loads(STATES_FILE.read_text(encoding="utf-8"))
    return frozenset(name.lower() for name in data["canonical"]) | frozenset(data["variants"])


def normalise_header(header: str) -> str:
    """Lower-case, turn - _ . / into spaces, collapse repeated spaces."""
    return " ".join(re.sub(r"[-_./]", " ", header.lower()).split())


def content_words(text: str) -> set[str]:
    return set(text.split()) - STOP_WORDS


def header_score(header: str, role: str) -> tuple[float, str]:
    """0.5 for an exact synonym, 0.3 if a meaningful word is shared, else 0."""
    normalised = normalise_header(header)
    if normalised in SYNONYMS[role]:
        return HEADER_EXACT, f"header '{header}' matches '{normalised}'"
    words = content_words(normalised)
    for synonym in SYNONYMS[role]:
        shared = words & content_words(synonym)
        if shared:
            return HEADER_PARTIAL, f"header '{header}' contains '{sorted(shared)[0]}'"
    return 0.0, ""


def profile_column(name: str, series: pd.Series) -> ColumnProfile:
    """Non-blank values from the first PROFILE_ROWS rows, and their numeric reading."""
    values = series.head(PROFILE_ROWS).dropna().astype(str).str.strip()
    values = values[values != ""].reset_index(drop=True)
    numbers = pd.to_numeric(values.str.replace(NUMBER_NOISE, "", regex=True), errors="coerce")
    return ColumnProfile(name=name, values=values, numbers=numbers)


def pct(share: float) -> str:
    return f"{share:.0%}"


def check_order_id(p: ColumnProfile) -> tuple[bool, str]:
    ratio = p.distinct / p.count if p.count else 0.0
    return ratio >= 0.5, f"{pct(ratio)} of values are distinct (needs 50%)"


def check_order_date(p: ColumnProfile) -> tuple[bool, str]:
    looks_like_date = p.values.map(lambda v: any(pat.match(v) for pat in DATE_PATTERNS))
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
    words = [w for w in STATUS_WORDS if p.values.str.lower().str.contains(w, regex=False).any()]
    passed = 0 < p.distinct <= 30 and bool(words)
    shown = ", ".join(words) if words else "none"
    return passed, f"{p.distinct} distinct values (max 30); status words found: {shown}"


def state_share(p: ColumnProfile) -> float:
    return p.share(p.values.str.lower().isin(state_names()))


def check_state(p: ColumnProfile) -> tuple[bool, str]:
    share = state_share(p)
    return share >= 0.6, f"{pct(share)} of values are known Indian states (needs 60%)"


def check_city(p: ColumnProfile) -> tuple[bool, str]:
    text, states = 1 - p.numeric_share(), state_share(p)
    passed = p.count > 0 and text >= 0.95 and states < 0.6
    return passed, f"{pct(text)} text values, {pct(states)} are state names (needs under 60%)"


def check_category(p: ColumnProfile) -> tuple[bool, str]:
    text = 1 - p.numeric_share()
    passed = p.count > 0 and text >= 0.95 and p.distinct <= 100
    return passed, f"{pct(text)} text values, {p.distinct} distinct (max 100)"


def check_sku(p: ColumnProfile) -> tuple[bool, str]:
    share = p.share(p.values.str.match(SKU_PATTERN))
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


def score(profile: ColumnProfile, role: str) -> Candidate:
    """Confidence = header score + value score, with the reasons for each part."""
    head, head_reason = header_score(profile.name, role)
    if profile.count == 0:
        passed, value_reason = False, "column is empty"
    else:
        passed, value_reason = VALUE_CHECKS[role](profile)
    confidence = round(head + (VALUES_PASS if passed else 0.0), 2)
    value_reason = ("values: " if passed else "values fail: ") + value_reason
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
    return list(dict.fromkeys(profile.values))[:SAMPLE_COUNT]


def best_unassigned(role: str, candidates: list[Candidate]) -> Candidate | None:
    for_role = [c for c in candidates if c.role == role]
    return max(for_role, key=lambda c: c.confidence, default=None)


def suggestion_for(
    role: str, chosen: dict[str, Candidate], candidates: list[Candidate],
    profiles: dict[str, ColumnProfile],
) -> RoleSuggestion:
    if role in chosen:
        c = chosen[role]
        return RoleSuggestion(role, c.column, c.confidence, c.reasons, samples(profiles[c.column]))
    best = best_unassigned(role, candidates)
    if best is None or best.confidence == 0:
        return RoleSuggestion(role, None, 0.0, ["no column looks like this role"], [])
    note = f"best candidate '{best.column}' scored {best.confidence:.2f}, below {SUGGEST_THRESHOLD}"
    if best.confidence >= SUGGEST_THRESHOLD:
        note = f"best candidate '{best.column}' was already used for another role"
    reasons = [note, *best.reasons]
    return RoleSuggestion(role, None, best.confidence, reasons, samples(profiles[best.column]))


def detect_roles(df: pd.DataFrame) -> DetectionResult:
    """Suggest a column for each role (FR-2.1, FR-2.2); blank when confidence is under 0.8."""
    profiles = {str(name): profile_column(str(name), df[name]) for name in df.columns}
    candidates = [score(p, role) for p in profiles.values() for role in ROLES]
    chosen = assign(candidates)
    roles = [suggestion_for(role, chosen, candidates, profiles) for role in ROLES]
    used = {c.column for c in chosen.values()}
    return DetectionResult(
        roles=roles,
        missing_required=[r for r in REQUIRED_ROLES if r not in chosen],
        unmapped_columns=[name for name in profiles if name not in used],
    )


def confirmed_roles(df: pd.DataFrame, mapping: dict[str, str]) -> DetectionResult:
    """Roles fixed in advance (the bundled sample): confidence 1.0, with sample values."""
    profiles = {role: profile_column(column, df[column]) for role, column in mapping.items()}
    roles = [
        RoleSuggestion(role, mapping[role], 1.0, ["pre-confirmed for the bundled sample"],
                       samples(profiles[role]))
        if role in mapping else RoleSuggestion(role, None, 0.0, ["not used by the sample"], [])
        for role in ROLES
    ]
    return DetectionResult(
        roles=roles,
        missing_required=[r for r in REQUIRED_ROLES if r not in mapping],
        unmapped_columns=[str(c) for c in df.columns if c not in set(mapping.values())],
    )
