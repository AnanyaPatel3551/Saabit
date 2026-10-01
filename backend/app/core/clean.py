"""Clean states, dates, duplicates and the cancelled flag, and record the fix log."""

import csv
import io
from dataclasses import astuple, dataclass

import pandas as pd
import pyarrow as pa

from app.core.ingest import ROW_HASH, release_memory
from app.core.states import fold, state_lookup

__all__ = ["ROW_HASH", "FixEntry", "clean", "fix_log_csv", "partial_months", "unknown_states"]

# Role -> canonical column (PRD Data model).
CANONICAL_COLUMNS = {
    "order_id": "order_id",
    "order_date": "order_date",
    "status": "status_raw",
    "amount": "amount",
    "qty": "qty",
    "state": "state",
    "city": "city",
    "category": "category",
    "sku": "sku",
    "fulfilment": "fulfilment",
    "channel": "channel",
}
COLUMN_ORDER = [
    "order_id", "order_date", "status_raw", "is_cancelled", "amount", "qty",
    "state", "city", "category", "sku", "fulfilment", "channel",
]
REQUIRED_ROLES = ("order_id", "order_date", "amount")
CANCELLED_STATUS = "Cancelled"  # the locked rule (FR-3.3): ANY line with exactly this status
PARTIAL_SHARE = 0.5  # FR-3.2: under half the median month's days or rows
DATE_PARTS = r"^(\d{1,4})[-/.](\d{1,2})[-/.](\d{2,4})"
AMOUNT_NOISE = r"₹|[Rr][Ss]\.?|INR|inr|,|\s"
QTY_NOISE = r",|\s"
DATE32 = pd.ArrowDtype(pa.date32())
FIX_FIELDS = ["rule", "column", "before", "after", "rows_affected"]


@dataclass(frozen=True)
class FixEntry:
    """One logged change (FR-3.4): what rule changed which column from what to what."""

    rule: str
    column: str
    before: str
    after: str
    rows_affected: int


def clean(df: pd.DataFrame, roles: dict[str, str]) -> tuple[pd.DataFrame, list[FixEntry]]:
    """Return the canonical, cleaned table and the log of every fix applied.

    df holds raw text cells named as in the file; roles maps role -> column name.
    If df has a ROW_HASH column (a hash of the full raw row), it decides which rows are
    identical; otherwise all columns of df are compared.
    """
    missing = [r for r in REQUIRED_ROLES if r not in roles]
    if missing:
        raise ValueError(f"missing required role(s): {', '.join(missing)}")
    log: list[FixEntry] = []
    work = to_canonical(df, roles)
    del df  # the caller may have handed over its only reference; let replaced columns go
    work = drop_identical_rows(work, log)
    work = parse_dates(work, log)
    release_memory()
    work["amount"] = parse_amount(work["amount"], log)
    if "qty" in work:
        work["qty"] = parse_qty(work["qty"], log)
    if "state" in work:
        work["state"] = normalise_states(work["state"], log)
    if "city" in work:
        work["city"] = normalise_cities(work["city"], log)
    if "status_raw" in work:
        work["is_cancelled"] = cancelled_flags(work["order_id"], work["status_raw"])
    log_partial_months(work["order_date"], log)
    columns = [c for c in COLUMN_ORDER if c in work.columns]
    return work[columns].reset_index(drop=True), log


def to_canonical(df: pd.DataFrame, roles: dict[str, str]) -> pd.DataFrame:
    """Keep only the confirmed columns, renamed to the Data model names."""
    work = pd.DataFrame({CANONICAL_COLUMNS[role]: df[column] for role, column in roles.items()})
    if ROW_HASH in df:
        work[ROW_HASH] = df[ROW_HASH]
    return work


def drop_identical_rows(work: pd.DataFrame, log: list[FixEntry]) -> pd.DataFrame:
    """Remove rows identical to an earlier row. Different lines of one order are kept."""
    key = [ROW_HASH] if ROW_HASH in work else list(work.columns)
    duplicate = work.duplicated(subset=key, keep="first")
    if duplicate.any():
        log.append(FixEntry("duplicate_row", "*", "identical copy of an earlier row", "removed",
                            int(duplicate.sum())))
    return work.loc[~duplicate].drop(columns=[ROW_HASH], errors="ignore")


def date_parts(text: pd.Series) -> tuple[pd.DataFrame, str, str]:
    """The three numbers of each a/b/c date, plus the separator and year width seen first.

    Extracted once and shared by date_order and to_dates.
    """
    parts = text.str.extract(DATE_PARTS)
    first = parts[0].dropna()
    if first.empty:
        return parts.astype("float64"), "-", "YYYY"
    position = first.index[0]
    sep = next(ch for ch in text[position] if ch in "-/.")
    year = "YYYY" if len(parts.at[position, 2]) == 4 else "YY"
    first_width_four = bool(first.str.len().eq(4).mean() >= 0.5)
    numbers = parts.apply(pd.to_numeric).astype("float64")
    return numbers, sep, "YYYY-FIRST" if first_width_four else year


def date_order(numbers: pd.DataFrame, sep: str, year: str) -> tuple[str, str]:
    """Decide how to read a/b/c dates from the values: 'ymd', 'mdy' or 'dmy', with a note."""
    matched = numbers[0].notna()
    if not matched.any():
        return "mixed", "no day/month pattern found; each value parsed on its own"
    if year == "YYYY-FIRST":
        return "ymd", f"year-first (YYYY{sep}MM{sep}DD)"
    first_is_day = int((numbers.loc[matched, 0] > 12).sum())
    second_is_day = int((numbers.loc[matched, 1] > 12).sum())
    if second_is_day > first_is_day:
        return "mdy", f"month-first (MM{sep}DD{sep}{year})"
    if first_is_day > second_is_day:
        return "dmy", f"day-first (DD{sep}MM{sep}{year})"
    return "dmy", f"day-first (DD{sep}MM{sep}{year}), assumed: every value fits both orders"


def to_dates(text: pd.Series, parts: pd.DataFrame, order: str) -> pd.Series:
    """Parse text into datetimes using the chosen order; failures become NaT."""
    if order == "ymd":
        year, month, day = parts[0], parts[1], parts[2]
    elif order == "mdy":
        month, day, year = parts[0], parts[1], parts[2]
    else:
        day, month, year = parts[0], parts[1], parts[2]
    year = year.where(year >= 100, year + 2000)
    frame = pd.DataFrame({"year": year, "month": month, "day": day})
    parsed = pd.to_datetime(frame, errors="coerce")
    other = parts[0].isna() & text.ne("")
    if other.any():
        parsed[other] = pd.to_datetime(
            text[other], errors="coerce", format="mixed", dayfirst=order != "mdy"
        ).dt.tz_localize(None)
    return parsed


def parse_dates(work: pd.DataFrame, log: list[FixEntry]) -> pd.DataFrame:
    """Parse order_date; rows that fail are dropped and logged by value (FR-3.2)."""
    text = work["order_date"].fillna("").str.strip()
    parts, sep, year = date_parts(text)
    order, note = date_order(parts, sep, year)
    parsed = to_dates(text, parts, order)
    del parts
    bad = parsed.isna()
    log.append(FixEntry("date_order", "order_date", "text dates", note, int((~bad).sum())))
    if bad.any():
        for value, count in counts_by_value(text[bad]):
            log.append(FixEntry("date_unparseable", "order_date", value, "row dropped", count))
        work, parsed = work.loc[~bad].copy(), parsed[~bad]
    work["order_date"] = parsed.dt.normalize().astype("datetime64[ms]").astype(DATE32)
    return work


def parse_amount(raw: pd.Series, log: list[FixEntry]) -> pd.Series:
    """Strip rupee symbols, Rs/INR and thousands separators, then read as a number."""
    stripped = raw.str.strip()
    present = stripped.notna() & stripped.ne("")
    cleaned = stripped.str.replace(AMOUNT_NOISE, "", regex=True)
    numbers = pd.to_numeric(cleaned, errors="coerce").astype("float64")
    changed = present & numbers.notna() & cleaned.ne(stripped)
    if changed.any():
        log.append(FixEntry("amount_cleaned", "amount", "currency symbols or separators",
                            "removed", int(changed.sum())))
    for value, count in counts_by_value(stripped[present & numbers.isna()]):
        log.append(FixEntry("amount_unparseable", "amount", value, "missing", count))
    return numbers


def parse_qty(raw: pd.Series, log: list[FixEntry]) -> pd.Series:
    """Whole numbers only; anything else becomes missing and is logged."""
    stripped = raw.str.strip()
    present = stripped.notna() & stripped.ne("")
    numbers = pd.to_numeric(stripped.str.replace(QTY_NOISE, "", regex=True), errors="coerce")
    numbers = numbers.astype("float64")
    whole = numbers.notna() & (numbers % 1 == 0)
    for value, count in counts_by_value(stripped[present & ~whole]):
        log.append(FixEntry("qty_not_integer", "qty", value, "missing", count))
    return numbers.where(whole).astype("Int64")


def normalise_states(raw: pd.Series, log: list[FixEntry]) -> pd.Series:
    """Map each spelling through states.json; unknown values are kept exactly and listed."""
    codes, uniques = pd.factorize(raw, sort=True)
    lookup = state_lookup()
    counts = pd.Series(codes[codes >= 0]).value_counts()
    mapped = []
    for index, value in enumerate(uniques):
        canonical = lookup.get(fold(value))
        rows = int(counts.get(index, 0))
        if canonical is None:
            log.append(FixEntry("state_unknown", "state", value, value, rows))
        elif canonical != value:
            log.append(FixEntry("state_normalised", "state", value, canonical, rows))
        mapped.append(canonical or value)
    values = pd.array(mapped + [None], dtype=raw.dtype)
    return pd.Series(values.take(codes), index=raw.index)


def city_key(value: str) -> str:
    """Matching key for a city spelling: single-spaced, trimmed and casefolded."""
    return " ".join(value.split()).casefold()


def normalise_cities(raw: pd.Series, log: list[FixEntry]) -> pd.Series:
    """Merge spellings that differ only in case or spaces into the most common one.

    Ties go to the alphabetically first spelling, so the result does not depend on row order.
    Different names (MUMBAI, NAVI MUMBAI) are never merged.
    """
    codes, uniques = pd.factorize(raw, sort=True)
    counts = pd.Series(codes[codes >= 0]).value_counts()
    rows = [int(counts.get(i, 0)) for i in range(len(uniques))]
    best: dict[str, tuple[int, str]] = {}
    for value, n in zip(uniques, rows, strict=True):
        key = city_key(value)
        if key not in best or (-n, value) < (-best[key][0], best[key][1]):
            best[key] = (n, value)
    mapped = []
    for value, n in zip(uniques, rows, strict=True):
        canonical = best[city_key(value)][1]
        if canonical != value:
            log.append(FixEntry("city_normalised", "city", value, canonical, n))
        mapped.append(canonical)
    values = pd.array(mapped + [None], dtype=raw.dtype)
    return pd.Series(values.take(codes), index=raw.index)


def cancelled_flags(order_id: pd.Series, status: pd.Series) -> pd.Series:
    """True on every line of an order where ANY line's status is exactly 'Cancelled'."""
    line = status.eq(CANCELLED_STATUS).fillna(False).astype(bool)
    return line.groupby(order_id, dropna=False, sort=False).transform("any").astype(bool)


def log_partial_months(dates: pd.Series, log: list[FixEntry]) -> None:
    """FR-3.2: flag months with under half the median month's active days or rows."""
    stamps = dates.astype("datetime64[ms]")
    month_key = stamps.dt.year * 100 + stamps.dt.month  # 202203 for March 2022
    stats = pd.DataFrame({"month": month_key, "day": stamps}).groupby("month")
    table = stats.agg(days=("day", "nunique"), rows=("day", "size"))
    median_days, median_rows = table["days"].median(), table["rows"].median()
    for key, row in table.iterrows():
        if row["days"] < PARTIAL_SHARE * median_days or row["rows"] < PARTIAL_SHARE * median_rows:
            month = f"{int(key) // 100}-{int(key) % 100:02d}"
            note = (f"flagged partial: {row['days']} days, {row['rows']} rows "
                    f"(median month {median_days:g} days, {median_rows:g} rows)")
            log.append(FixEntry("partial_month", "order_date", month, note, int(row["rows"])))


def counts_by_value(values: pd.Series) -> list[tuple[str, int]]:
    """(value, count) pairs sorted by value, so the log order never changes between runs."""
    if values.empty:
        return []
    grouped = values.astype("string").fillna("").groupby(values.astype("string").fillna(""))
    return [(str(value), int(count)) for value, count in grouped.size().sort_index().items()]


def partial_months(log: list[FixEntry]) -> list[str]:
    """Months flagged partial, e.g. ['2022-03']."""
    return [e.before for e in log if e.rule == "partial_month"]


def unknown_states(log: list[FixEntry]) -> list[str]:
    """State values not found in states.json (kept as they are)."""
    return [e.before for e in log if e.rule == "state_unknown"]


def fix_log_csv(log: list[FixEntry]) -> str:
    """The fix log as CSV text with a header row."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(FIX_FIELDS)
    writer.writerows(astuple(entry) for entry in log)
    return buffer.getvalue()
