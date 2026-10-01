import pytest

from app.core.numcheck import allowed_values, check, extract_numbers
from app.core.plan import Plan


@pytest.mark.parametrize(
    ("text", "value", "kind"),
    [
        ("₹2,39,53,534", 23953534, "money"),
        ("2,39,53,534", 23953534, "count"),
        ("23,953,534", 23953534, "count"),
        ("₹2.40 Cr", 24_000_000, "money"),
        ("2.4 crore", 24_000_000, "money"),
        ("Rs 2.62 Cr", 26_200_000, "money"),
        ("₹69 lakh", 6_900_000, "money"),
        ("Rs. 1,249.50", 1249.50, "money"),
        ("INR 99", 99, "money"),
        ("14.3%", 14.3, "percent"),
        ("36% more often", 36, "percent"),
        ("17.46 per cent", 17.46, "percent"),
        ("4.6 percentage points", 4.6, "percent"),
        ("1,20,378 orders", 120378, "count"),
        ("₹3,250", 3250, "money"),
    ],
)
def test_parses_indian_number_formats(text: str, value: float, kind: str) -> None:
    numbers = extract_numbers(text)

    assert len(numbers) == 1, numbers
    assert numbers[0].value == pytest.approx(value)
    assert numbers[0].kind == kind


def test_dates_split_into_their_parts() -> None:
    assert [n.value for n in extract_numbers("from 2022-05-01 to 31 May 2022")] == [
        2022, 5, 1, 31, 2022]


def test_36_percent_more_often_is_allowed_from_17_5_vs_12_9() -> None:
    plan = Plan(metric="cancellation_rate", group_by=["fulfilment"])
    rows = [{"fulfilment": "Merchant", "value": 17.5, "orders": 36376},
            {"fulfilment": "Amazon", "value": 12.9, "orders": 84002}]
    allowed = allowed_values(rows, plan, "Amazon vs Merchant cancellation")

    ok, unmatched = check("Merchant orders are cancelled 36% more often than Amazon orders "
                          "(17.5% vs 12.9%), a gap of 4.6 percentage points.", allowed)

    assert ok, unmatched


def test_year_in_question_is_not_a_claim() -> None:
    plan = Plan(metric="revenue", date_range={"start": "2022-05-01", "end": "2022-05-31"})
    allowed = allowed_values([{"value": 23953534.0, "orders": 39221}], plan,
                             "What was revenue in May 2022?")

    ok, unmatched = check("Revenue in May 2022 was ₹2.40 Cr across 39,221 orders.", allowed)

    assert ok, unmatched


def test_numbers_in_group_keys_are_allowed() -> None:
    plan = Plan(metric="revenue", group_by=["month"])
    rows = [{"month": "2022-04", "value": 26234520.0, "orders": 45858}]

    ok, _ = check("Revenue in Apr 2022 was ₹2.62 Cr.", allowed_values(rows, plan, ""))

    assert ok


def test_cr_and_lakh_forms_are_allowed_at_the_stated_precision() -> None:
    allowed = allowed_values([{"value": 6919284.3, "orders": 17185}], Plan(metric="revenue"), "")

    assert check("₹69.19 lakh", allowed)[0]
    assert check("₹69 lakh", allowed)[0]
    assert check("₹0.69 Cr", allowed)[0]
    assert not check("₹70 lakh", allowed)[0]
    assert not check("₹69.20 lakh", allowed)[0]


def test_invented_number_is_unmatched() -> None:
    allowed = allowed_values([{"value": 23953534.0, "orders": 39221}], Plan(metric="revenue"), "")

    ok, unmatched = check("Revenue was ₹2.40 Cr, up 12% on April.", allowed)

    assert not ok
    assert [n.text for n in unmatched] == ["12%"]


def test_rounding_must_match_what_was_written() -> None:
    allowed = allowed_values([{"value": 14.2759, "orders": 120378}],
                             Plan(metric="cancellation_rate"), "")

    assert check("14.3%", allowed)[0]
    assert check("14.28%", allowed)[0]
    assert check("14%", allowed)[0]
    assert not check("14.2%", allowed)[0]
    assert not check("15%", allowed)[0]
