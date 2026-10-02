import ast
import json
import random
import shutil
from datetime import timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pytest
import sqlglot
from sqlglot import exp

from app.core import compile_pandas, compile_sql
from app.core.metrics import DIMENSIONS, MAX_ROWS, METRICS
from app.core.pipeline import dataset_info, load_context, run_plan
from app.core.plan import Plan, PlanError, UnknownFilterValue
from app.core.verify import compare

MARCH_NOTE = "Mar 2022 is a partial month: only 1 day of data (31 Mar)"

SEED = 20260930
FILTERABLE = [name for name, d in DIMENSIONS.items() if d.filterable]


def sample_id(cache: Path) -> str:
    return json.loads((cache / "metadata.json").read_text("utf-8"))["dataset_id"]


@pytest.fixture(scope="module")
def subset_cache(real_sample_cache: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Every 20th cleaned line of the real sample (all months, many groups), for speed."""
    folder = tmp_path_factory.mktemp("subset_cache")
    for name in ("metadata.json", "fixes.csv"):
        shutil.copy(real_sample_cache / name, folder / name)
    clean = pd.read_parquet(real_sample_cache / "clean.parquet")
    clean.iloc[::20].reset_index(drop=True).to_parquet(folder / "clean.parquet", index=False)
    compile_sql.create_query_db(folder)
    return folder


def random_plan(rng: random.Random, values: dict[str, list[str]], low, high) -> Plan:
    plan: dict = {"metric": rng.choice(list(METRICS)),
                  "group_by": rng.sample(list(DIMENSIONS), k=rng.choice([0, 1, 1, 2]))}
    filters = []
    for _ in range(rng.choice([0, 0, 1, 2])):
        column = rng.choice(FILTERABLE)
        op = rng.choice(["eq", "in", "not_in"])
        count = 1 if op == "eq" else rng.randint(1, min(4, len(values[column])))
        chosen = rng.sample(values[column], count)
        filters.append({"column": column, "op": op,
                        "values": [v.upper() if rng.random() < 0.3 else v for v in chosen]})
    plan["filters"] = filters
    if rng.random() < 0.5:
        span = (high - low).days
        start = low + timedelta(days=rng.randint(0, span))
        plan["date_range"] = {"start": str(start),
                              "end": str(start + timedelta(days=rng.randint(0, 40)))}
    if rng.random() < 0.6:
        plan["sort"] = {"by": rng.choice(["value", "key"]), "dir": rng.choice(["asc", "desc"])}
    if rng.random() < 0.5:
        plan["limit"] = rng.randint(1, 50)
    return Plan.model_validate(plan)


def test_engines_agree_on_200_random_valid_plans(subset_cache: Path, tmp_path: Path) -> None:
    rng = random.Random(SEED)
    context = load_context(sample_id(subset_cache), tmp_path, subset_cache)
    info = dataset_info(context)
    values = {c: compile_sql.distinct_values(context.query_db, c) for c in FILTERABLE}
    failures = []
    for number in range(200):
        plan = random_plan(rng, values, info.date_min, info.date_max)
        try:
            card = run_plan(context.dataset_id, plan, tmp_path, subset_cache)
        except PlanError as error:  # e.g. a date range past the data
            assert "no data between" in error.message
            continue
        if not card.verified:
            failures.append((number, plan.model_dump(mode="json"), card.mismatches[:3]))
    assert failures == []


def test_mismatch_is_flagged_not_verified(
    sample_cache: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = compile_pandas.metric_value
    monkeypatch.setattr(compile_pandas, "metric_value",
                        lambda totals, metric: real(totals, metric) * 1.01)
    plan = Plan(metric="revenue", group_by=["fulfilment"])

    card = run_plan(sample_id(sample_cache), plan, tmp_path, sample_cache)

    assert card.verified is False
    assert card.result == []
    assert card.sql_result and card.pandas_result
    assert any(m.startswith("value for") for m in card.mismatches)


def test_a_group_missing_from_one_engine_is_a_mismatch() -> None:
    sql = pd.DataFrame({"state": ["Goa", "Kerala"], "value": [1.0, 2.0], "orders": [1, 1]})
    pandas = pd.DataFrame({"state": ["Goa"], "value": [1.0], "orders": [1]})

    result = compare(sql, pandas, ["state"])

    assert result.verified is False
    assert "Kerala appears only in the SQL result" in result.mismatches[0]


def test_values_within_tolerance_are_verified() -> None:
    sql = pd.DataFrame({"value": [23953534.0], "orders": [10]})
    pandas = pd.DataFrame({"value": [23953534.004], "orders": [10]})

    assert compare(sql, pandas, []).verified is True


def test_filter_value_is_snapped_case_insensitively(sample_cache: Path, tmp_path: Path) -> None:
    plan = Plan(metric="orders", filters=[{"column": "state", "op": "in",
                                           "values": ["maharashtra", "KARNATAKA", "RJ"]}])

    card = run_plan(sample_id(sample_cache), plan, tmp_path, sample_cache)

    assert card.plan["filters"][0]["values"] == ["Maharashtra", "Karnataka", "Rajasthan"]
    assert card.verified


def test_unknown_filter_value_lists_valid_options(sample_cache: Path, tmp_path: Path) -> None:
    plan = Plan(metric="orders", filters=[{"column": "state", "values": ["Keralaa"]}])

    with pytest.raises(UnknownFilterValue) as error:
        run_plan(sample_id(sample_cache), plan, tmp_path, sample_cache)

    assert "Kerala" in error.value.options
    assert "Closest matches" in error.value.message


def test_date_range_outside_data_is_clipped_with_caveat(
    real_sample_cache: Path, tmp_path: Path
) -> None:
    plan = Plan(metric="orders", date_range={"start": "2022-01-01", "end": "2022-04-15"})

    card = run_plan(sample_id(real_sample_cache), plan, tmp_path, real_sample_cache)

    assert card.plan["date_range"] == {"start": "2022-03-31", "end": "2022-04-15"}
    assert any("clipped" in c for c in card.caveats)


def test_date_range_with_no_data_at_all_is_refused(real_sample_cache: Path, tmp_path: Path) -> None:
    plan = Plan(metric="orders", date_range={"start": "2023-01-01", "end": "2023-01-31"})

    with pytest.raises(PlanError, match="covers 2022-03-31 to 2022-06-29"):
        run_plan(sample_id(real_sample_cache), plan, tmp_path, real_sample_cache)


def test_partial_month_adds_caveat(real_sample_cache: Path, tmp_path: Path) -> None:
    plan = Plan(metric="revenue", group_by=["month"])

    card = run_plan(sample_id(real_sample_cache), plan, tmp_path, real_sample_cache)

    assert any(c.startswith(MARCH_NOTE) for c in card.caveats)
    assert [r["month"] for r in card.result] == ["2022-03", "2022-04", "2022-05", "2022-06"]


def test_no_partial_month_caveat_when_range_excludes_it(
    real_sample_cache: Path, tmp_path: Path
) -> None:
    plan = Plan(metric="revenue", date_range={"start": "2022-05-01", "end": "2022-05-31"})

    card = run_plan(sample_id(real_sample_cache), plan, tmp_path, real_sample_cache)

    assert not any("partial month" in c for c in card.caveats)


def test_small_group_adds_caveat(sample_cache: Path, tmp_path: Path) -> None:
    plan = Plan(metric="orders", group_by=["state"])

    card = run_plan(sample_id(sample_cache), plan, tmp_path, sample_cache)

    assert any(c.startswith("Based on fewer than 30 orders") for c in card.caveats)


def test_cleaned_column_in_filter_adds_caveat(sample_cache: Path, tmp_path: Path) -> None:
    plan = Plan(metric="orders", filters=[{"column": "state", "values": ["Maharashtra"]}])

    card = run_plan(sample_id(sample_cache), plan, tmp_path, sample_cache)

    assert any(c.startswith("State was cleaned before this was worked out") for c in card.caveats)


def test_sql_has_limit_and_is_select_only(subset_cache: Path) -> None:
    rng = random.Random(SEED + 1)
    context = load_context(sample_id(subset_cache), subset_cache, subset_cache)
    info = dataset_info(context)
    values = {c: compile_sql.distinct_values(context.query_db, c) for c in FILTERABLE}
    forbidden = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
                 exp.Command, exp.Copy)
    columns = compile_sql.table_columns(context.query_db)
    for _ in range(100):
        plan = random_plan(rng, values, info.date_min, info.date_max)
        sql = compile_sql.compile_plan(plan, columns).sql(dialect="duckdb")
        parsed = sqlglot.parse_one(sql, read="duckdb")
        assert isinstance(parsed, exp.Select)
        limit = parsed.args["limit"].expression
        assert 1 <= int(limit.this) <= MAX_ROWS
        assert not any(parsed.find_all(*forbidden))


def test_query_connection_is_read_only(sample_cache: Path) -> None:
    with compile_sql.connect(sample_cache / compile_sql.QUERY_DB) as con:
        with pytest.raises(duckdb.Error):
            con.execute(exp.Create(kind="TABLE", this=exp.to_table("x"),
                                   expression=exp.select("1")).sql(dialect="duckdb"))


def test_slow_query_is_stopped_by_the_timeout(
    sample_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compile_sql, "TIMEOUT_SECONDS", 0.2)
    slow = exp.select(exp.Sum(this=exp.column("range"))).from_(
        exp.func("range", exp.Literal.number(10**12)))

    with pytest.raises(compile_sql.QueryTimeout):
        compile_sql.execute(sample_cache / compile_sql.QUERY_DB, slow)


def test_pandas_engine_does_not_import_compile_sql() -> None:
    tree = ast.parse(Path(compile_pandas.__file__).read_text(encoding="utf-8"))
    imported = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    imported += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not any("compile_sql" in name for name in imported)


def test_pandas_engine_loads_only_the_columns_a_plan_needs(
    sample_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []
    original = pd.read_parquet

    def spy(path: object, columns: list[str] | None = None, **kwargs: object) -> pd.DataFrame:
        seen.append(list(columns or []))
        return original(path, columns=columns, **kwargs)

    monkeypatch.setattr(compile_pandas.pd, "read_parquet", spy)
    plan = Plan(metric="orders", filters=[{"column": "state", "values": ["Goa"]}])
    available = compile_sql.table_columns(sample_cache / compile_sql.QUERY_DB)

    compile_pandas.run_plan_pandas(sample_cache / "clean.parquet", plan, available)

    assert seen == [["is_cancelled", "order_id", "state"]]


@pytest.mark.parametrize(
    ("plan", "message"),
    [
        ({"metric": "profit"}, "Unknown metric"),
        ({"metric": "orders", "limit": 501}, "limit is 501"),
        ({"metric": "orders", "group_by": ["state", "city", "sku"]}, "at most 2"),
        ({"status": "unsupported", "unsupported_reason": "no cost column"}, "status"),
    ],
)
def test_invalid_plans_are_refused_with_a_reason(
    plan: dict, message: str, sample_cache: Path, tmp_path: Path
) -> None:
    with pytest.raises(PlanError, match=message):
        run_plan(sample_id(sample_cache), Plan.model_validate(plan), tmp_path, sample_cache)


# Order counts follow the metric's definition (metrics.Metric.orders_counted). The notebook's
# answer key: 17,185 of 120,378 orders are cancelled, so 103,193 are not.
def test_revenue_orders_count_excludes_cancelled_in_both_engines(
    real_sample_cache: Path, tmp_path: Path
) -> None:
    for metric in ("revenue", "aov", "units"):
        card = run_plan(sample_id(real_sample_cache), Plan(metric=metric), tmp_path,
                        real_sample_cache)

        assert card.verified, metric  # SQL and pandas agree on the count too
        assert card.result[0]["orders"] == 103193, metric


def test_cancellation_rate_orders_count_includes_cancelled(
    real_sample_cache: Path, tmp_path: Path
) -> None:
    plan = Plan(metric="cancellation_rate",
                filters=[{"column": "state", "op": "eq", "values": ["Rajasthan"]}])

    card = run_plan(sample_id(real_sample_cache), plan, tmp_path, real_sample_cache)

    assert card.result[0]["orders"] == 2512  # the PRD's "14.2% of 2,512 orders"


def test_all_time_total_has_no_partial_month_note(real_sample_cache: Path, tmp_path: Path) -> None:
    card = run_plan(sample_id(real_sample_cache), Plan(metric="revenue"), tmp_path,
                    real_sample_cache)

    assert not any("partial month" in c for c in card.caveats)


def test_a_range_inside_march_keeps_the_partial_month_note(
    real_sample_cache: Path, tmp_path: Path
) -> None:
    plan = Plan(metric="orders", date_range={"start": "2022-03-01", "end": "2022-03-31"})

    card = run_plan(sample_id(real_sample_cache), plan, tmp_path, real_sample_cache)

    assert any(c.startswith(MARCH_NOTE) for c in card.caveats)
