"""Run a plan end to end: validate, snap, compute twice, verify, save an evidence card."""

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from app.core import compile_pandas, compile_sql, evidence, storage, verify
from app.core.plan import DatasetInfo, Plan, snap_values, validate_plan

CARDS_DIR = "cards"
FIXES_FILE = "fixes.csv"
# Log rules that describe the data rather than change values in a column.
INFORMATIONAL_RULES = {"date_order", "partial_month", "state_unknown"}


class DatasetNotReady(Exception):
    """The dataset has not been cleaned yet, so there is nothing to query."""

    code = "not_cleaned"

    def __init__(self, dataset_id: str) -> None:
        self.message = (f"Dataset '{dataset_id}' has not been cleaned yet. "
                        "Confirm its columns first.")
        super().__init__(self.message)


@dataclass(frozen=True)
class DatasetContext:
    """Where a cleaned dataset lives and what cleaning recorded about it."""

    dataset_id: str
    folder: Path  # holds clean.parquet, query.duckdb, fixes.csv
    cards_dir: Path
    roles: frozenset[str]
    partial_months: list[str]
    cleaned_columns: dict[str, str]

    @property
    def parquet(self) -> Path:
        return self.folder / compile_sql.CLEAN_FILE

    @property
    def query_db(self) -> Path:
        return self.folder / compile_sql.QUERY_DB


def load_context(dataset_id: str, storage_root: Path, sample_cache: Path) -> DatasetContext:
    """Find a cleaned dataset: the shared sample (in its cache) or an upload (in storage)."""
    sample_meta = sample_cache / storage.METADATA_FILE
    metadata = json.loads(sample_meta.read_text("utf-8")) if sample_meta.is_file() else None
    if metadata is not None and metadata.get("dataset_id") == dataset_id:
        folder = sample_cache
    else:
        metadata = storage.read_metadata(storage_root, dataset_id)
        folder = storage.dataset_dir(storage_root, dataset_id)
    check = metadata.get("data_check")
    if check is None or not (folder / compile_sql.CLEAN_FILE).is_file():
        raise DatasetNotReady(dataset_id)
    if not (folder / compile_sql.QUERY_DB).is_file():
        compile_sql.create_query_db(folder)
    return DatasetContext(
        dataset_id=dataset_id,
        folder=folder,
        cards_dir=storage.dataset_dir(storage_root, dataset_id) / CARDS_DIR,
        roles=frozenset(r["role"] for r in metadata["roles"] if r["column"]),
        partial_months=list(check.get("partial_months", [])),
        cleaned_columns=cleaned_columns(folder / FIXES_FILE),
    )


def cleaned_columns(fixes_csv: Path) -> dict[str, str]:
    """Columns whose values cleaning changed, with a short description for caveats."""
    if not fixes_csv.is_file():
        return {}
    changes: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    with fixes_csv.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["rule"] in INFORMATIONAL_RULES or row["column"] == "*":
                continue
            changes[row["column"]][0] += 1
            changes[row["column"]][1] += int(row["rows_affected"])
    return {column: f"{entries} value(s) changed across {rows:,} rows"
            for column, (entries, rows) in changes.items()}


def dataset_info(context: DatasetContext, source: compile_sql.Source | None = None) -> DatasetInfo:
    """What validation needs: confirmed roles, date bounds, and a way to list values."""
    db = source if source is not None else context.query_db
    low, high = compile_sql.date_bounds(db)
    return DatasetInfo(
        roles=context.roles,
        date_min=low,
        date_max=high,
        values=lambda column: compile_sql.distinct_values(db, column),
    )


@dataclass(frozen=True)
class Workspace:
    """One dataset plus where its data and cards live: runs predefined plans as cards."""

    dataset_id: str
    storage_root: Path
    sample_cache: Path
    cards_dir: Path

    def context(self) -> DatasetContext:
        return load_context(self.dataset_id, self.storage_root, self.sample_cache)

    def run(self, plan: dict) -> evidence.EvidenceCard:
        """Run a plan given as a dict; PlanError means the dataset cannot answer it."""
        return run_plan(self.dataset_id, Plan.model_validate(plan), self.storage_root,
                        self.sample_cache, self.cards_dir)


def card_dirs(context: DatasetContext, sample_cache: Path) -> list[Path]:
    """Where a dataset's cards may be: its storage folder, then (for the sample) the cache."""
    return [context.cards_dir, sample_cache / CARDS_DIR]


def run_plan(
    dataset_id: str,
    plan: Plan,
    storage_root: Path,
    sample_cache: Path,
    cards_dir: Path | None = None,
) -> evidence.EvidenceCard:
    """Validate and snap the plan, run both engines, verify, and save the evidence card.

    cards_dir overrides where the card is saved (the sample's insight cards live in its cache).
    """
    context = load_context(dataset_id, storage_root, sample_cache)
    with compile_sql.connect(context.query_db) as con:  # one read-only connection per run
        info = dataset_info(context, con)
        plan, caveats = validate_plan(plan, info)
        plan = snap_values(plan, info)
        columns = compile_sql.table_columns(con)
        sql_result, sql_text = compile_sql.run_plan_sql(con, plan, columns)
        row_count = compile_sql.count_source_rows(con, plan)
    pandas_result, pandas_code = compile_pandas.run_plan_pandas(context.parquet, plan, columns)
    check = verify.compare(sql_result, pandas_result, list(plan.group_by))
    agreed = check.rows if check.verified else check.sql_rows
    caveats += verify.caveats_for(plan, agreed, context.partial_months, context.cleaned_columns)
    card = evidence.EvidenceCard(
        card_id=evidence.new_card_id(dataset_id),
        dataset_id=dataset_id,
        plan=plan.model_dump(mode="json"),
        sql=sql_text,
        pandas_code=pandas_code,
        verified=check.verified,
        result=check.rows,
        caveats=caveats,
        row_count=row_count,
        sql_result=None if check.verified else check.sql_rows,
        pandas_result=None if check.verified else check.pandas_rows,
        mismatches=check.mismatches,
    )
    evidence.save_card(cards_dir or context.cards_dir, card)
    return card
