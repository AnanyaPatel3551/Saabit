"""Insight, data-check and caveat text reads like the answers: month names not codes, Indian
grouping, real plurals, Cr/lakh amounts, percentage points, and every partial month."""

import re

from app.core.capability import capability_report
from app.core.insights import e5
from app.core.templates import clean_up_text, plural

CHECK = {
    "rows_in": 128975, "rows_out": 128975, "date_min": "2022-03-31", "date_max": "2022-06-29",
    "partial_months": ["2022-03"], "unknown_states": [],
    "fixes": [{"rule": "state_normalised", "entries": 53, "rows_affected": 124093},
              {"rule": "city_normalised", "entries": 1, "rows_affected": 2},
              {"rule": "qty_not_integer", "entries": 3, "rows_affected": 3},
              {"rule": "partial_month", "entries": 1, "rows_affected": 171}],
}


def test_clean_up_counts_use_indian_grouping_and_real_plurals() -> None:
    expected = "53 state spellings fixed in 1,24,093 rows"
    assert clean_up_text("state_normalised", 53, 124093) == expected
    assert clean_up_text("city_normalised", 1, 1) == "1 city spelling merged in 1 row"
    assert clean_up_text("qty_not_integer", 3, 3) == "3 quantities that are not whole numbers noted"
    assert plural(1, "row") == "1 row"


def test_the_data_fixes_card_lists_every_partial_month_by_name() -> None:
    text = e5(CHECK)["text"]

    assert "Cleaning kept 1,28,975 rows of 1,28,975 rows." in text
    assert "53 state spellings fixed in 1,24,093 rows" in text
    assert "Mar 2022 has only 1 day of data (31 Mar)" in text
    assert "Jun 2022 has 29 of 30 days of data (missing 30 Jun)" in text
    assert not re.search(r"\b20\d\d-\d\d\b", text)
    assert "(s)" not in text and "normalised" not in text


def test_capability_reasons_have_no_bracketed_plurals_and_name_products() -> None:
    report = capability_report({"order_id", "order_date", "amount", "state", "sku"})
    texts = [i.topic + " " + i.reason for i in report.can_answer + report.cannot_answer]

    assert not any("(s)" in t for t in texts)
    assert any(t.startswith("breakdown by product (SKU)") for t in texts)
