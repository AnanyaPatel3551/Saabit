import pandas as pd

from app.api.datasets import SAMPLE_ROLES
from app.core.detect import ROLES, SUGGEST_THRESHOLD, DetectionResult, detect_roles
from app.core.ingest import read_upload
from tests.conftest import FIXTURES


def detect_fixture(name: str) -> DetectionResult:
    return detect_roles(read_upload((FIXTURES / name).read_bytes(), name))


def suggested(result: DetectionResult) -> dict[str, str | None]:
    return {r.role: r.column for r in result.roles}


def by_role(result: DetectionResult) -> dict:
    return {r.role: r for r in result.roles}


def test_detects_amazon_roles() -> None:
    result = detect_fixture("amazon_300.csv")

    assert suggested(result) == SAMPLE_ROLES
    assert result.missing_required == []


def test_amazon_exact_headers_with_matching_values_score_full_confidence() -> None:
    roles = by_role(detect_fixture("amazon_300.csv"))

    assert roles["status"].confidence == 1.0
    assert roles["order_date"].confidence == 1.0
    assert roles["amount"].confidence == 1.0


def test_detects_roles_with_other_header_names() -> None:
    result = detect_fixture("shopify_orders.csv")
    roles = suggested(result)

    assert roles["order_date"] == "Created at"
    assert roles["amount"] == "Total"
    assert roles["status"] == "Financial Status"
    assert roles["state"] == "Shipping Province"
    assert roles["city"] == "Shipping City"
    assert roles["qty"] == "Lineitem quantity"
    assert roles["sku"] == "Lineitem sku"


def test_partial_header_match_with_matching_values_scores_exactly_the_threshold() -> None:
    roles = by_role(detect_fixture("shopify_orders.csv"))

    assert roles["status"].confidence == 0.8
    assert roles["qty"].confidence == 0.8


def test_required_role_without_a_confident_column_is_reported_missing() -> None:
    result = detect_fixture("shopify_orders.csv")

    assert suggested(result)["order_id"] is None
    assert result.missing_required == ["order_id"]


def test_ambiguous_column_is_left_blank() -> None:
    df = pd.DataFrame({
        "Order ID": [f"A-{i}" for i in range(50)],
        "Date": ["soon", "n/a", "tbc", "later", "unknown"] * 10,
        "Value": [f"{100 + i}.50" for i in range(50)],
    })

    roles = by_role(detect_roles(df))

    assert roles["order_date"].column is None
    assert roles["order_date"].confidence == 0.5
    assert roles["amount"].column is None
    assert roles["amount"].confidence == 0.5


def test_blank_role_still_explains_its_best_candidate() -> None:
    df = pd.DataFrame({
        "Order ID": [f"A-{i}" for i in range(50)],
        "Value": [f"{i}.5" for i in range(50)],
    })

    amount = by_role(detect_roles(df))["amount"]

    assert amount.column is None
    assert any("Value" in reason for reason in amount.reasons)
    assert any("below" in reason for reason in amount.reasons)


def test_each_column_is_used_for_at_most_one_role() -> None:
    df = pd.DataFrame({
        "Order ID": [f"A-{i}" for i in range(40)],
        "Fulfilment Channel": ["Amazon", "Merchant"] * 20,
    })

    roles = suggested(detect_roles(df))

    assert [roles["fulfilment"], roles["channel"]].count("Fulfilment Channel") == 1


def test_no_column_is_suggested_twice_on_real_files() -> None:
    names = ["amazon_300.csv", "shopify_orders.csv", "orders.xlsx", "latin1.csv", "semicolon.csv"]
    for name in names:
        columns = [c for c in suggested(detect_fixture(name)).values() if c is not None]
        assert len(columns) == len(set(columns)), name


def test_returns_every_role_in_a_fixed_order() -> None:
    result = detect_fixture("semicolon.csv")

    assert [r.role for r in result.roles] == list(ROLES)


def test_confidence_is_between_zero_and_one_and_suggestions_meet_threshold() -> None:
    for name in ["amazon_300.csv", "shopify_orders.csv"]:
        for role in detect_fixture(name).roles:
            assert 0.0 <= role.confidence <= 1.0
            if role.column is not None:
                assert role.confidence >= SUGGEST_THRESHOLD


def test_suggestion_has_reasons_and_three_sample_values() -> None:
    status = by_role(detect_fixture("amazon_300.csv"))["status"]

    assert len(status.samples) == 3
    assert len(set(status.samples)) == 3
    assert any("header" in reason for reason in status.reasons)
    assert any("distinct" in reason for reason in status.reasons)


def test_unmapped_columns_are_listed() -> None:
    result = detect_fixture("shopify_orders.csv")

    assert "Vendor" in result.unmapped_columns
    assert "Name" in result.unmapped_columns
    assert "Total" not in result.unmapped_columns


def test_detects_roles_in_xlsx_dates_and_numbers() -> None:
    roles = suggested(detect_fixture("orders.xlsx"))

    assert roles["order_id"] == "Order ID"
    assert roles["order_date"] == "Order Date"
    assert roles["amount"] == "Amount"


def test_state_needs_sixty_percent_of_values_to_match_the_dictionary() -> None:
    mostly_states = ["Rajasthan"] * 6 + ["Nowhere"] * 4
    mostly_other = ["Rajasthan"] * 5 + ["Nowhere"] * 5
    ids = [f"A-{i}" for i in range(10)]

    passes = by_role(detect_roles(pd.DataFrame({"Order ID": ids, "State": mostly_states})))["state"]
    fails = by_role(detect_roles(pd.DataFrame({"Order ID": ids, "State": mostly_other})))["state"]

    assert passes.column == "State"
    assert fails.column is None
