"""Compile a plan to a sqlglot query and run it on DuckDB."""

import threading
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv
from sqlglot import exp

from app.core.metrics import DIMENSIONS, MAX_ROWS, METRICS, SORT_DECIMALS
from app.core.plan import Plan

TABLE = "clean"
QUERY_DB = "query.duckdb"
CLEAN_FILE = "clean.parquet"
DIALECT = "duckdb"
TIMEOUT_SECONDS = 10.0
DUCKDB_CONFIG = {"memory_limit": "128MB", "threads": 1}
KEY_COLUMNS_ORDER = ("value", "orders")


class QueryTimeout(Exception):
    """A query ran longer than TIMEOUT_SECONDS and was interrupted."""

    code = "query_timeout"

    def __init__(self) -> None:
        self.message = f"The query took longer than {TIMEOUT_SECONDS:g} seconds and was stopped."
        super().__init__(self.message)


def col(name: str) -> exp.Column:
    return exp.column(name)


def text(value: str) -> exp.Literal:
    return exp.Literal.string(value)


def number(value: float) -> exp.Literal:
    return exp.Literal.number(value)


def create_query_db(folder: Path) -> Path:
    """Write query.duckdb: a single view 'clean' over clean.parquet, for read-only queries."""
    db_path = folder / QUERY_DB
    source = exp.select("*").from_(
        exp.func("read_parquet", text((folder / CLEAN_FILE).resolve().as_posix()))
    )
    view = exp.Create(kind="VIEW", this=exp.to_table(TABLE), replace=True, expression=source)
    with duckdb.connect(str(db_path)) as con:
        con.execute(view.sql(dialect=DIALECT))
    return db_path


def connect(db_path: Path) -> duckdb.DuckDBPyConnection:
    """A read-only connection: DuckDB rejects any write through it (FR-5.3)."""
    return duckdb.connect(str(db_path), read_only=True, config=DUCKDB_CONFIG)


Source = Path | duckdb.DuckDBPyConnection  # a query.duckdb path, or an open read-only connection


def execute(source: Source, query: exp.Select) -> pd.DataFrame:
    """Run one SELECT with a timeout. A timer interrupts the connection after 10 seconds.

    Pass an open connection to run several queries without reconnecting each time.
    """
    if not isinstance(query, exp.Select):
        raise TypeError("only SELECT statements are run")
    con = connect(source) if isinstance(source, Path) else source
    timer = threading.Timer(TIMEOUT_SECONDS, con.interrupt)
    timer.start()
    try:
        return con.execute(query.sql(dialect=DIALECT)).fetch_df()
    except duckdb.InterruptException as exc:
        raise QueryTimeout() from exc
    finally:
        timer.cancel()
        if isinstance(source, Path):
            con.close()


def cancelled_flag(columns: set[str]) -> exp.Expression:
    """is_cancelled, or FALSE when the file had no status column."""
    return col("is_cancelled") if "is_cancelled" in columns else exp.false()


def key_expression(dimension: str) -> exp.Expression:
    """The group key for a dimension, written as metrics.DIMENSIONS describes."""
    if dimension == "month":
        return exp.func("strftime", col("order_date"), text("%Y-%m"))
    if dimension == "week":
        monday = exp.func("date_trunc", text("week"), col("order_date"))
        return exp.func("strftime", monday, text("%Y-%m-%d"))
    return col(DIMENSIONS[dimension].column)


def count_distinct(value: exp.Expression) -> exp.Count:
    return exp.Count(this=exp.Distinct(expressions=[value]))


def when(condition: exp.Expression, value: exp.Expression) -> exp.Case:
    return exp.Case().when(condition, value)


def metric_expression(metric: str, columns: set[str]) -> exp.Expression:
    """The aggregate for one metric (definitions in metrics.METRICS)."""
    cancelled = cancelled_flag(columns)
    live = exp.Not(this=cancelled.copy())
    zero = number(0)
    if metric == "orders":
        return count_distinct(col("order_id"))
    if metric == "revenue":
        return exp.Coalesce(this=exp.Sum(this=when(live, col("amount"))), expressions=[zero])
    if metric == "units":
        return exp.Coalesce(this=exp.Sum(this=when(live, col("qty"))), expressions=[zero])
    if metric == "aov":
        revenue = exp.Coalesce(this=exp.Sum(this=when(live.copy(), col("amount"))),
                               expressions=[zero.copy()])
        live_orders = count_distinct(when(live.copy(), col("order_id")))
        return exp.Div(this=revenue, expression=exp.Nullif(this=live_orders, expression=zero))
    if metric == "cancelled_orders":
        return count_distinct(when(cancelled.copy(), col("order_id")))
    if metric == "cancellation_rate":
        cancelled_orders = count_distinct(when(cancelled.copy(), col("order_id")))
        share = exp.Mul(this=number(100.0), expression=cancelled_orders)
        return exp.Div(this=share, expression=exp.Nullif(
            this=count_distinct(col("order_id")), expression=zero))
    raise ValueError(f"no SQL for metric {metric}")


def where_clause(plan: Plan) -> exp.Expression | None:
    """Date range (inclusive), filters, and no blank group values."""
    conditions: list[exp.Expression] = []
    if plan.date_range is not None:
        start = exp.cast(text(plan.date_range.start.isoformat()), "DATE")
        end = exp.cast(text(plan.date_range.end.isoformat()), "DATE")
        conditions.append(col("order_date").between(start, end))
    for f in plan.filters:
        column = col(DIMENSIONS[f.column].column)
        values = [text(v) for v in f.values]
        if f.op == "eq":
            conditions.append(column.eq(values[0]))
        elif f.op == "in":
            conditions.append(column.isin(*values))
        else:
            present = exp.Not(this=column.copy().is_(exp.null()))
            conditions.append(exp.and_(present, exp.Not(this=column.copy().isin(*values))))
    for dimension in plan.group_by:
        conditions.append(exp.Not(this=key_expression(dimension).is_(exp.null())))
    return exp.and_(*conditions) if conditions else None


def orders_expression(metric: str, columns: set[str]) -> exp.Expression:
    """The "orders" column: distinct orders, or only those not cancelled (orders_counted)."""
    if METRICS[metric].orders_counted == "not_cancelled":
        live = exp.Not(this=cancelled_flag(columns))
        return count_distinct(when(live, col("order_id")))
    return count_distinct(col("order_id"))


def compile_plan(plan: Plan, columns: set[str]) -> exp.Select:
    """plan -> one SELECT: group keys, value, orders; sorted and limited (FR-5.1)."""
    keys = [key_expression(d) for d in plan.group_by]
    value = metric_expression(plan.metric or "", columns)
    projections = [exp.alias_(k.copy(), d) for k, d in zip(keys, plan.group_by, strict=True)]
    projections += [exp.alias_(value.copy(), "value"),
                    exp.alias_(orders_expression(plan.metric or "", columns), "orders")]
    query = exp.select(*projections).from_(TABLE)
    where = where_clause(plan)
    if where is not None:
        query = query.where(where)
    if keys:
        query = query.group_by(*[k.copy() for k in keys]).order_by(*order_terms(plan, keys, value))
    return query.limit(min(plan.limit or MAX_ROWS, MAX_ROWS))


def order_terms(plan: Plan, keys: list[exp.Expression], value: exp.Expression) -> list[exp.Ordered]:
    """Sort rule from metrics.SHARED_RULES: value (rounded) then keys, or keys only."""
    if plan.sort is not None and plan.sort.by == "value":
        rounded = exp.func("round", value.copy(), number(SORT_DECIMALS))
        first = [exp.Ordered(this=rounded, desc=plan.sort.dir == "desc", nulls_first=False)]
        return first + [exp.Ordered(this=k.copy(), desc=False, nulls_first=False) for k in keys]
    descending = plan.sort is not None and plan.sort.dir == "desc"
    return [exp.Ordered(this=k.copy(), desc=descending, nulls_first=False) for k in keys]


def run_plan_sql(db_path: Source, plan: Plan, columns: set[str]) -> tuple[pd.DataFrame, str]:
    """Compile and run the plan; return the result table and the exact SQL text."""
    query = compile_plan(plan, columns)
    return execute(db_path, query), query.sql(dialect=DIALECT, pretty=True)


def source_rows_query(plan: Plan) -> exp.Select:
    """The cleaned lines behind a result: same dates and filters, every column."""
    query = exp.select("*").from_(TABLE)
    conditions = where_clause(plan.model_copy(update={"group_by": []}))
    if conditions is not None:
        query = query.where(conditions)
    return query.order_by(col("order_date"), col("order_id"))


def count_source_rows(db_path: Source, plan: Plan) -> int:
    query = exp.select(exp.alias_(exp.Count(this=exp.Star()), "n")).from_(
        source_rows_query(plan).order_by().subquery("source")
    )
    return int(execute(db_path, query)["n"].iloc[0])


def source_rows_page(db_path: Source, plan: Plan, page: int, page_size: int) -> pd.DataFrame:
    query = source_rows_query(plan).limit(page_size).offset((page - 1) * page_size)
    return execute(db_path, query)


def source_rows_csv(db_path: Path, plan: Plan) -> Iterator[bytes]:
    """Stream every source row as CSV, one DuckDB batch at a time."""
    con = connect(db_path)
    try:
        reader = con.execute(source_rows_query(plan).sql(dialect=DIALECT)).to_arrow_reader(
            batch_size=10_000
        )
        sink = pa.BufferOutputStream()
        writer = pacsv.CSVWriter(sink, reader.schema)
        for batch in reader:
            writer.write_batch(batch)
            yield sink.getvalue().to_pybytes()
            sink = pa.BufferOutputStream()
            writer = pacsv.CSVWriter(sink, reader.schema, write_options=pacsv.WriteOptions(
                include_header=False))
        writer.close()
    finally:
        con.close()


def distinct_values(db_path: Source, column: str) -> list[str]:
    """Distinct non-blank values of one canonical column, sorted."""
    query = (exp.select(exp.alias_(col(column), "v")).distinct().from_(TABLE)
             .where(exp.Not(this=col(column).is_(exp.null()))).order_by(col(column)))
    return [str(v) for v in execute(db_path, query)["v"]]


def distinct_count(db_path: Source, column: str) -> int:
    """How many distinct non-blank values one canonical column has."""
    query = exp.select(exp.alias_(count_distinct(col(column)), "n")).from_(TABLE)
    return int(execute(db_path, query)["n"].iloc[0])


def date_bounds(db_path: Source) -> tuple[date, date]:
    query = exp.select(exp.alias_(exp.Min(this=col("order_date")), "lo"),
                       exp.alias_(exp.Max(this=col("order_date")), "hi")).from_(TABLE)
    row = execute(db_path, query).iloc[0]
    return pd.Timestamp(row["lo"]).date(), pd.Timestamp(row["hi"]).date()


def table_columns(db_path: Source) -> set[str]:
    return set(execute(db_path, exp.select("*").from_(TABLE).limit(0)).columns)
