from pathlib import Path

import pandas as pd
import pytest

from app.core.clean import ROW_HASH, FixEntry, clean, fix_log_csv, partial_months

ROLES = {
    "order_id": "Order ID",
    "order_date": "Date",
    "amount": "Amount",
    "status": "Status",
    "state": "ship-state",
    "qty": "Qty",
}


def orders(rows: list[dict]) -> pd.DataFrame:
    """Build a raw text DataFrame with the Amazon column names; missing cells are blank."""
    defaults = {"Order ID": "A-1", "Date": "04-30-22", "Amount": "100.00", "Status": "Shipped",
                "ship-state": "Maharashtra", "Qty": "1"}
    return pd.DataFrame([{**defaults, **r} for r in rows], dtype="string[pyarrow]")


def entries(log: list[FixEntry], rule: str) -> list[FixEntry]:
    return [e for e in log if e.rule == rule]


def test_columns_are_renamed_to_the_canonical_data_model() -> None:
    df, _ = clean(orders([{}]), ROLES)

    assert list(df.columns) == [
        "order_id", "order_date", "status_raw", "is_cancelled", "amount", "qty", "state",
    ]


def test_rajasthan_variants_merge_into_one_state() -> None:
    raw = orders([{"Order ID": f"R-{i}", "ship-state": s}
                  for i, s in enumerate(["RAJASTHAN", "Rajasthan", "rajasthan", "RJ",
                                         "Rajsthan", "Rajshthan", " rajsthan "])])

    df, log = clean(raw, ROLES)

    assert set(df["state"]) == {"Rajasthan"}
    changed = {e.before: e.rows_affected for e in entries(log, "state_normalised")}
    assert changed["RJ"] == 1
    assert changed["Rajshthan"] == 1
    assert "Rajasthan" not in changed


def test_unknown_state_is_kept_and_listed() -> None:
    df, log = clean(orders([{"Order ID": "A-1", "ship-state": "APO"},
                            {"Order ID": "A-2", "ship-state": "APO"}]), ROLES)

    assert list(df["state"]) == ["APO", "APO"]
    unknown = entries(log, "state_unknown")
    assert [(e.before, e.after, e.rows_affected) for e in unknown] == [("APO", "APO", 2)]


def test_cancelled_rule_applies_to_all_lines_of_an_order() -> None:
    raw = orders([
        {"Order ID": "A-1", "Status": "Cancelled"},
        {"Order ID": "A-1", "Status": "Shipped", "Amount": "200.00"},
        {"Order ID": "A-2", "Status": "Shipped"},
    ])

    df, _ = clean(raw, ROLES)

    by_order = df.groupby("order_id")["is_cancelled"].agg(set).to_dict()
    assert by_order == {"A-1": {True}, "A-2": {False}}


def test_cancelled_needs_status_exactly_cancelled() -> None:
    raw = orders([{"Order ID": "A-1", "Status": "cancelled"},
                  {"Order ID": "A-2", "Status": "Shipped - Returned to Seller"}])

    df, _ = clean(raw, ROLES)

    assert not df["is_cancelled"].any()


def test_without_a_status_role_there_is_no_cancelled_flag() -> None:
    roles = {k: v for k, v in ROLES.items() if k != "status"}

    df, _ = clean(orders([{}]), roles)

    assert "is_cancelled" not in df.columns
    assert "status_raw" not in df.columns


def test_multi_item_orders_are_not_deduplicated() -> None:
    raw = orders([
        {"Order ID": "A-1", "Amount": "100.00"},
        {"Order ID": "A-1", "Amount": "100.00"},
    ])
    raw[ROW_HASH] = pd.Series([111, 222], dtype="uint64")

    df, log = clean(raw, ROLES)

    assert len(df) == 2
    assert entries(log, "duplicate_row") == []


def test_identical_rows_are_removed_and_logged() -> None:
    raw = orders([{"Order ID": "A-1"}, {"Order ID": "A-1"}, {"Order ID": "A-2"}])
    raw[ROW_HASH] = pd.Series([111, 111, 333], dtype="uint64")

    df, log = clean(raw, ROLES)

    assert list(df["order_id"]) == ["A-1", "A-2"]
    assert [e.rows_affected for e in entries(log, "duplicate_row")] == [1]


def test_without_row_hashes_identical_rows_compare_every_column() -> None:
    raw = orders([{"Order ID": "A-1"}, {"Order ID": "A-1"}, {"Order ID": "A-1", "Qty": "2"}])

    df, _ = clean(raw, ROLES)

    assert len(df) == 2


def test_month_first_dates_are_detected_from_the_values() -> None:
    raw = orders([{"Order ID": "A-1", "Date": "04-30-22"}, {"Order ID": "A-2", "Date": "05-01-22"}])

    df, log = clean(raw, ROLES)

    assert [str(d) for d in df["order_date"]] == ["2022-04-30", "2022-05-01"]
    assert entries(log, "date_order")[0].after == "month-first (MM-DD-YY)"


def test_day_first_dates_are_detected_from_the_values() -> None:
    raw = orders([{"Order ID": "A-1", "Date": "30/04/2022"},
                  {"Order ID": "A-2", "Date": "01/05/2022"}])

    df, _ = clean(raw, ROLES)

    assert [str(d) for d in df["order_date"]] == ["2022-04-30", "2022-05-01"]


def test_ambiguous_dates_assume_day_first_and_say_so() -> None:
    raw = orders([{"Order ID": "A-1", "Date": "04/05/2022"}])

    df, log = clean(raw, ROLES)

    assert str(df["order_date"].iloc[0]) == "2022-05-04"
    assert "assumed" in entries(log, "date_order")[0].after


def test_iso_dates_with_times_are_parsed() -> None:
    raw = orders([{"Order ID": "A-1", "Date": "2024-03-05 14:22:00 +0530"}])

    df, _ = clean(raw, ROLES)

    assert str(df["order_date"].iloc[0]) == "2024-03-05"


def test_unparseable_dates_are_dropped_and_logged() -> None:
    raw = orders([{"Order ID": "A-1", "Date": "04-30-22"}, {"Order ID": "A-2", "Date": "soon"},
                  {"Order ID": "A-3", "Date": "soon"}, {"Order ID": "A-4", "Date": None}])

    df, log = clean(raw, ROLES)

    assert list(df["order_id"]) == ["A-1"]
    dropped = {e.before: e.rows_affected for e in entries(log, "date_unparseable")}
    assert dropped == {"soon": 2, "": 1}


def test_amount_with_rupee_symbol_is_parsed() -> None:
    raw = orders([{"Order ID": "A-1", "Amount": "₹1,249.50"},
                  {"Order ID": "A-2", "Amount": "Rs. 1,00,000"},
                  {"Order ID": "A-3", "Amount": "INR 99"},
                  {"Order ID": "A-4", "Amount": "647.62"}])

    df, log = clean(raw, ROLES)

    assert list(df["amount"]) == [1249.50, 100000.0, 99.0, 647.62]
    assert sum(e.rows_affected for e in entries(log, "amount_cleaned")) == 3


def test_blank_amount_stays_missing_and_bad_amount_is_logged() -> None:
    raw = orders([{"Order ID": "A-1", "Amount": None}, {"Order ID": "A-2", "Amount": "free"}])

    df, log = clean(raw, ROLES)

    assert df["amount"].isna().all()
    unparseable = [(e.before, e.rows_affected) for e in entries(log, "amount_unparseable")]
    assert unparseable == [("free", 1)]


def test_qty_is_an_integer() -> None:
    raw = orders([{"Order ID": "A-1", "Qty": "2"}, {"Order ID": "A-2", "Qty": "1.0"},
                  {"Order ID": "A-3", "Qty": "1.5"}])

    df, log = clean(raw, ROLES)

    assert str(df["qty"].dtype) == "Int64"
    assert list(df["qty"].iloc[:2]) == [2, 1]
    assert pd.isna(df["qty"].iloc[2])
    assert [e.before for e in entries(log, "qty_not_integer")] == ["1.5"]


def test_march_is_flagged_partial() -> None:
    rows = [{"Order ID": "M-1", "Date": "03-31-22"}]
    rows += [{"Order ID": f"A-{d}", "Date": f"04-{d:02d}-22"} for d in range(1, 31)]
    rows += [{"Order ID": f"B-{d}", "Date": f"05-{d:02d}-22"} for d in range(1, 32)]
    rows += [{"Order ID": f"C-{d}", "Date": f"06-{d:02d}-22"} for d in range(1, 30)]

    _, log = clean(orders(rows), ROLES)

    assert partial_months(log) == ["2022-03"]
    march = entries(log, "partial_month")[0]
    assert (march.before, march.rows_affected) == ("2022-03", 1)


def test_fix_log_serialises_to_csv() -> None:
    _, log = clean(orders([{"ship-state": "RJ"}]), ROLES)

    text = fix_log_csv(log)

    assert text.splitlines()[0] == "rule,column,before,after,rows_affected"
    assert "state_normalised,state,RJ,Rajasthan,1" in text


def test_cleaning_is_deterministic(tmp_path: Path) -> None:
    raw = orders([{"Order ID": f"A-{i % 7}", "ship-state": s, "Status": st}
                  for i, (s, st) in enumerate(zip(["RJ", "apo", "Kerala"] * 5,
                                                  ["Shipped", "Cancelled", "Shipped"] * 5,
                                                  strict=True))])

    first_df, first_log = clean(raw.copy(), ROLES)
    second_df, second_log = clean(raw.copy(), ROLES)

    pd.testing.assert_frame_equal(first_df, second_df)
    assert first_log == second_log
    first_df.to_parquet(tmp_path / "a.parquet", index=False)
    second_df.to_parquet(tmp_path / "b.parquet", index=False)
    assert (tmp_path / "a.parquet").read_bytes() == (tmp_path / "b.parquet").read_bytes()


@pytest.mark.parametrize("role", ["order_id", "order_date", "amount"])
def test_clean_refuses_to_run_without_a_required_role(role: str) -> None:
    roles = {k: v for k, v in ROLES.items() if k != role}

    with pytest.raises(ValueError, match=role):
        clean(orders([{}]), roles)
