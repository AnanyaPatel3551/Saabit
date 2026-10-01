import pytest

from app.core.metrics import METRICS
from app.core.numcheck import allowed_values, check
from app.core.plan import Plan
from app.core.templates import format_count, format_inr, format_pct, template_sentence


@pytest.mark.parametrize(
    ("value", "short", "expected"),
    [
        (23953534, False, "₹2,39,53,534"),
        (23953534, True, "₹2.40 Cr"),
        (6919284.3, True, "₹69.19 lakh"),
        (648.56, False, "₹648.56"),
        (99, True, "₹99"),
        (1234567.0, False, "₹12,34,567"),
    ],
)
def test_format_inr(value: float, short: bool, expected: str) -> None:
    assert format_inr(value, short=short) == expected


def test_format_pct_and_count() -> None:
    assert format_pct(14.2759) == "14.3%"
    assert format_pct(17.46082, decimals=2) == "17.46%"
    assert format_count(120378) == "1,20,378"
    assert format_count(999) == "999"


def rows_for(group_by: list[str], metric: str) -> list[dict]:
    keys = {"month": ["2022-04", "2022-05", "2022-06"],
            "week": ["2022-04-25", "2022-05-02", "2022-05-09"],
            "state": ["Maharashtra", "Karnataka", "Telangana"],
            "fulfilment": ["Amazon", "Merchant", "Amazon"]}
    values = {"revenue": [26234520.0, 23953534.0, 21390530.0], "orders": [45858, 39221, 35141],
              "units": [44000, 38000, 34000], "aov": [648.56, 610.7, 608.71],
              "cancelled_orders": [5900, 6880, 4991],
              "cancellation_rate": [12.8604, 17.5445, 14.2759]}
    rows = []
    for i in range(3):
        row = {d: keys[d][i] for d in group_by}
        row.update(value=float(values[metric][i]), orders=[45858, 39221, 35141][i])
        rows.append(row)
    return rows


GROUPINGS = [[], ["state"], ["month"], ["week"], ["state", "fulfilment"]]


@pytest.mark.parametrize("metric", list(METRICS))
@pytest.mark.parametrize("group_by", GROUPINGS, ids=lambda g: "+".join(g) or "none")
def test_every_metric_and_grouping_has_a_template(metric: str, group_by: list[str]) -> None:
    plan = Plan(metric=metric, group_by=group_by,
                date_range={"start": "2022-04-01", "end": "2022-06-29"})
    rows = rows_for(group_by, metric)[: 1 if not group_by else 3]

    text = template_sentence(plan, rows)

    assert text and text.endswith(".")
    ok, unmatched = check(text, allowed_values(rows, plan, ""))
    assert ok, (text, unmatched)


def test_top_n_template_names_the_leader() -> None:
    plan = Plan(metric="orders", group_by=["state"], sort={"by": "value", "dir": "desc"}, limit=1)

    text = template_sentence(plan, [{"state": "Maharashtra", "value": 20780.0, "orders": 20780}])

    assert text == "Maharashtra has the highest orders at 20,780."


def test_filter_and_dates_appear_in_the_template() -> None:
    plan = Plan(metric="cancellation_rate",
                filters=[{"column": "state", "values": ["Rajasthan"]}],
                date_range={"start": "2022-05-01", "end": "2022-05-31"})

    text = template_sentence(plan, [{"value": 14.2118, "orders": 2512}])

    assert "Rajasthan" in text and "1 May 2022" in text and "31 May 2022" in text
    assert "14.2%" in text and "2,512 orders" in text


def test_empty_result_template_has_no_number_claims() -> None:
    plan = Plan(metric="orders", filters=[{"column": "state", "values": ["Goa"]}])

    text = template_sentence(plan, [])

    assert text.startswith("No orders match")
