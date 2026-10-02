"""Compute a plan with pandas, independently of the SQL engine.

This module must not import compile_sql, and no function here is shared with it: the two
engines implement metrics.METRICS and metrics.SHARED_RULES separately, so a bug in one is
caught when their results disagree (PRD D3, FR-5.2).
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa

from app.core.metrics import DIMENSIONS, MAX_ROWS, METRICS, SORT_DECIMALS
from app.core.plan import Plan

METRIC_COLUMNS = {
    "orders": (),
    "revenue": ("amount",),
    "units": ("qty",),
    "aov": ("amount",),
    "cancelled_orders": (),
    "cancellation_rate": (),
}


def needed_columns(plan: Plan, available: set[str]) -> list[str]:
    """Only the parquet columns this plan touches."""
    names = {"order_id", *METRIC_COLUMNS[plan.metric or ""]}
    names |= {DIMENSIONS[f.column].column for f in plan.filters}
    names |= {DIMENSIONS[d].column for d in plan.group_by}
    if plan.date_range is not None:
        names.add("order_date")
    if "is_cancelled" in available:
        names.add("is_cancelled")
    return sorted(names & available)


def load(parquet: Path, plan: Plan, available: set[str]) -> pd.DataFrame:
    """Read only the needed columns; dates become numpy datetimes, text stays Arrow strings."""
    df = pd.read_parquet(parquet, columns=needed_columns(plan, available),
                         dtype_backend="pyarrow")
    if "order_date" in df:
        dates = pa.array(df["order_date"].array).cast(pa.timestamp("ms"))
        df["order_date"] = dates.to_numpy(zero_copy_only=False)
    return df


def select_lines(df: pd.DataFrame, plan: Plan) -> pd.DataFrame:
    """Apply the date range (inclusive) and the filters to the order lines."""
    keep = pd.Series(True, index=df.index)
    if plan.date_range is not None:
        start = pd.Timestamp(plan.date_range.start)
        end = pd.Timestamp(plan.date_range.end)
        keep &= (df["order_date"] >= start) & (df["order_date"] <= end)
    for f in plan.filters:
        values = df[DIMENSIONS[f.column].column]
        listed = values.isin(f.values).fillna(False).astype(bool)
        if f.op in ("eq", "in"):
            keep &= listed
        else:
            keep &= values.notna().astype(bool) & ~listed
    return df.loc[keep.to_numpy()]


def group_key(df: pd.DataFrame, dimension: str) -> pd.Series:
    """Group key text per line. Dates are formatted once per distinct value, not per line."""
    if dimension == "month":
        return label_each(df["order_date"].dt.to_period("M").dt.start_time, "%Y-%m")
    if dimension == "week":
        monday = df["order_date"] - pd.to_timedelta(df["order_date"].dt.weekday, unit="D")
        return label_each(monday, "%Y-%m-%d")
    return df[DIMENSIONS[dimension].column].astype("string")


def label_each(stamps: pd.Series, pattern: str) -> pd.Series:
    codes, uniques = pd.factorize(stamps)
    labels = pd.Index(uniques).strftime(pattern).tolist()
    return pd.Series(pd.array(labels + [None], dtype="string").take(codes), index=stamps.index)


def work_table(df: pd.DataFrame, plan: Plan) -> pd.DataFrame:
    """One row per line: group keys plus the pieces each metric needs."""
    if "is_cancelled" in df:
        cancelled = df["is_cancelled"].fillna(False).astype(bool).to_numpy()
    else:
        cancelled = np.zeros(len(df), dtype=bool)
    ids = df["order_id"].astype("string")
    table = pd.DataFrame({d: group_key(df, d) for d in plan.group_by}, index=df.index)
    table["order_id"] = ids
    table["live_order"] = ids.where(~cancelled)
    table["cancelled_order"] = ids.where(cancelled)
    if "amount" in df:
        table["live_amount"] = df["amount"].astype("float64").where(~cancelled)
    if "qty" in df:
        table["live_qty"] = df["qty"].astype("float64").where(~cancelled)
    return table.dropna(subset=list(plan.group_by)) if plan.group_by else table


def summarise(table: pd.DataFrame) -> dict[str, pd.Series | float]:
    """Per-group totals (or whole-table totals when there is no grouping)."""
    parts = {
        "orders": ("order_id", "nunique"),
        "live_orders": ("live_order", "nunique"),
        "cancelled_orders": ("cancelled_order", "nunique"),
    }
    if "live_amount" in table:
        parts["revenue"] = ("live_amount", "sum")
    if "live_qty" in table:
        parts["units"] = ("live_qty", "sum")
    return parts


def compute(table: pd.DataFrame, plan: Plan) -> pd.DataFrame:
    parts = summarise(table)
    if plan.group_by:
        totals = table.groupby(list(plan.group_by), sort=False, dropna=True).agg(**parts)
        totals = totals.reset_index()
    else:
        totals = pd.DataFrame([{name: getattr(table[source], how)()
                                for name, (source, how) in parts.items()}])
    totals["value"] = metric_value(totals, plan.metric or "")
    # "orders" counts what the metric counts (metrics.Metric.orders_counted)
    if METRICS[plan.metric or ""].orders_counted == "not_cancelled":
        totals["orders"] = totals["live_orders"]
    columns = [*plan.group_by, "value", "orders"]
    return totals[columns]


def metric_value(totals: pd.DataFrame, metric: str) -> pd.Series:
    """The metric per row, from the totals (definitions in metrics.METRICS)."""
    if metric == "orders":
        return totals["orders"].astype("float64")
    if metric == "revenue":
        return totals["revenue"].astype("float64")
    if metric == "units":
        return totals["units"].astype("float64")
    if metric == "aov":
        live = totals["live_orders"].astype("float64")
        return (totals["revenue"].astype("float64") / live).where(live > 0)
    if metric == "cancelled_orders":
        return totals["cancelled_orders"].astype("float64")
    if metric == "cancellation_rate":
        orders = totals["orders"].astype("float64")
        return (100.0 * totals["cancelled_orders"].astype("float64") / orders).where(orders > 0)
    raise ValueError(f"no pandas computation for metric {metric}")


def order_and_limit(result: pd.DataFrame, plan: Plan) -> pd.DataFrame:
    keys = list(plan.group_by)
    if keys:
        if plan.sort is not None and plan.sort.by == "value":
            result = result.assign(_rank=result["value"].round(SORT_DECIMALS))
            result = result.sort_values(["_rank", *keys],
                                        ascending=[plan.sort.dir == "asc", *[True] * len(keys)],
                                        na_position="last", kind="mergesort").drop(columns="_rank")
        else:
            ascending = plan.sort is None or plan.sort.dir == "asc"
            result = result.sort_values(keys, ascending=ascending, na_position="last",
                                        kind="mergesort")
    return result.head(min(plan.limit or MAX_ROWS, MAX_ROWS)).reset_index(drop=True)


def snippet(plan: Plan, columns: list[str]) -> str:
    """A short, readable description of the pandas steps that were run."""
    lines = [f"df = pd.read_parquet('clean.parquet', columns={columns})"]
    if plan.date_range is not None:
        lines.append(f"df = df[df.order_date.between('{plan.date_range.start}', "
                     f"'{plan.date_range.end}')]")
    for f in plan.filters:
        column = DIMENSIONS[f.column].column
        test = f"df.{column}.isin({f.values})"
        lines.append(f"df = df[{test}]" if f.op != "not_in"
                     else f"df = df[df.{column}.notna() & ~{test}]")
    live = "~df.is_cancelled" if "is_cancelled" in columns else "all lines"
    lines.append(f"# live lines: {live}")
    measures = {
        "orders": "df.order_id.nunique()",
        "revenue": "df.amount[live].sum()",
        "units": "df.qty[live].sum()",
        "aov": "df.amount[live].sum() / df.order_id[live].nunique()",
        "cancelled_orders": "df.order_id[df.is_cancelled].nunique()",
        "cancellation_rate": "100 * df.order_id[df.is_cancelled].nunique() / df.order_id.nunique()",
    }
    measure = measures[plan.metric or ""]
    if plan.group_by:
        lines.append(f"result = df.groupby({list(plan.group_by)}).apply(lambda df: {measure})")
    else:
        lines.append(f"result = {measure}")
    return "\n".join(lines)


def run_plan_pandas(parquet: Path, plan: Plan, available: set[str]) -> tuple[pd.DataFrame, str]:
    """Run the plan with pandas; return the result table and a readable snippet."""
    columns = needed_columns(plan, available)
    df = select_lines(load(parquet, plan, available), plan)
    result = order_and_limit(compute(work_table(df, plan), plan), plan)
    return result, snippet(plan, columns)
