"""Helpers used by more than one route module."""

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.api.errors import InvalidRoles
from app.api.schemas import CapabilityOut, DataCheckOut, DatasetOut, FixSummaryOut, RoleOut
from app.core import capability, clean, compile_sql, detect, ingest
from app.core.storage import RAW_STEM

CLEAN_FILE = "clean.parquet"
FIXES_FILE = "fixes.csv"


def describe(
    dataset_id: str, filename: str, size_bytes: int, rows: int, columns: list[str],
    detection: detect.DetectionResult, confirmed: bool,
) -> DatasetOut:
    """Build the metadata record stored in metadata.json and returned by the API."""
    return DatasetOut(
        dataset_id=dataset_id,
        filename=filename,
        size_bytes=size_bytes,
        rows=rows,
        created_at=datetime.now(UTC),
        columns=columns,
        roles=[RoleOut.model_validate(r) for r in detection.roles],
        roles_confirmed=confirmed,
        missing_required=detection.missing_required,
        unmapped_columns=detection.unmapped_columns,
    )


def validate_roles(chosen: dict[str, str | None], columns: list[str]) -> dict[str, str]:
    """Check the user's final roles; return role -> column for the roles that are used."""
    unknown_roles = sorted(set(chosen) - set(detect.ROLES))
    if unknown_roles:
        raise InvalidRoles(f"Unknown role(s): {', '.join(unknown_roles)}.")
    roles = {role: column for role, column in chosen.items() if column}
    missing_columns = sorted(c for c in roles.values() if c not in columns)
    if missing_columns:
        raise InvalidRoles(f"These columns are not in the file: {', '.join(missing_columns)}.")
    used = defaultdict(list)
    for role, column in roles.items():
        used[column].append(role)
    doubled = {c: r for c, r in used.items() if len(r) > 1}
    if doubled:
        column, both = next(iter(sorted(doubled.items())))
        raise InvalidRoles(f"Column '{column}' is used for more than one role: {', '.join(both)}.")
    missing = [r for r in detect.REQUIRED_ROLES if r not in roles]
    if missing:
        raise InvalidRoles(f"Choose a column for every required role: {', '.join(missing)}.")
    return roles


def source_file(folder: Path) -> Path:
    """The file cleaning reads: the UTF-8 working copy if one was made, else the raw upload."""
    working = folder / ingest.UTF8_COPY
    if working.is_file():
        return working
    return next(folder.glob(f"{RAW_STEM}.*"))


def fix_summary(log: list[clean.FixEntry]) -> list[FixSummaryOut]:
    """One line per rule, in the order rules first appear in the log."""
    totals: dict[str, list[int]] = {}
    for entry in log:
        rows, entries = totals.setdefault(entry.rule, [0, 0])
        totals[entry.rule] = [rows + entry.rows_affected, entries + 1]
    return [FixSummaryOut(rule=r, rows_affected=t[0], entries=t[1]) for r, t in totals.items()]


def clean_dataset(
    dataset_id: str, source: Path, roles: dict[str, str], out_dir: Path
) -> DataCheckOut:
    """Load, clean, save clean.parquet and fixes.csv in out_dir, and build the data check."""
    raw, skipped = ingest.load_rows(source, list(dict.fromkeys(roles.values())))
    return clean_loaded(dataset_id, raw, skipped, roles, out_dir)


def clean_loaded(
    dataset_id: str, raw: pd.DataFrame, skipped: int, roles: dict[str, str], out_dir: Path
) -> DataCheckOut:
    """Clean rows that are already loaded (see ingest.load_rows) and save the results.

    The caller must not keep its own reference to raw, so memory can be freed.
    """
    rows_in = len(raw) + skipped
    # Pass the only reference into clean(), so replaced text columns can be freed as it goes.
    owned = [raw]
    del raw
    cleaned, log = clean.clean(owned.pop(), roles)
    ingest.release_memory()
    if skipped:
        log.insert(0, clean.FixEntry("malformed_row", "*", "wrong number of fields", "removed",
                                     skipped))
    pq.write_table(pa.Table.from_pandas(cleaned, preserve_index=False), out_dir / CLEAN_FILE)
    compile_sql.create_query_db(out_dir)
    (out_dir / FIXES_FILE).write_text(clean.fix_log_csv(log), encoding="utf-8")
    rows_out = len(cleaned)
    del cleaned
    ingest.release_memory()
    report = capability.capability_report(set(roles))
    return DataCheckOut(
        dataset_id=dataset_id,
        rows_in=rows_in,
        rows_out=rows_out,
        partial_months=clean.partial_months(log),
        unknown_states=clean.unknown_states(log),
        fixes=fix_summary(log),
        capability=CapabilityOut.model_validate(report),
    )
