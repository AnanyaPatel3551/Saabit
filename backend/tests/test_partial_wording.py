"""A partial month is never presented as a weak or strong month (labels only, values unchanged).

The sample runs 31 Mar to 29 Jun 2022: March holds 1 day and June 29 of 30 days.
"""

from datetime import date

from app.core import numcheck, verify
from app.core.coverage import partial_coverage
from app.core.narrate import write_answer
from app.core.plan import Plan
from app.core.templates import template_sentence

PARTIAL = partial_coverage(date(2022, 3, 31), date(2022, 6, 29))
TREND = Plan(metric="revenue", group_by=["month"])
TREND_ROWS = [
    {"month": "2022-03", "value": 94810.0, "orders": 158},
    {"month": "2022-04", "value": 26234520.0, "orders": 45858},
    {"month": "2022-05", "value": 23953534.0, "orders": 39221},
    {"month": "2022-06", "value": 21390530.0, "orders": 35141},
]


class Writer:
    def __init__(self, sentence: str) -> None:
        self.sentence = sentence
        self.user = ""

    def __call__(self, system: str, user: str) -> dict:
        self.user = user
        return {"sentence": self.sentence}


def test_the_trend_template_says_what_each_partial_month_holds() -> None:
    sentence = template_sentence(TREND, TREND_ROWS, PARTIAL)

    assert "Mar 2022 (only 1 day of data, 31 Mar) ₹94,810" in sentence
    assert "Jun 2022 (29 of 30 days, missing 30 Jun) ₹2,13,90,530" in sentence
    assert "Apr 2022 ₹2,62,34,520" in sentence


def test_a_date_range_inside_june_says_june_is_missing_a_day() -> None:
    plan = Plan(metric="revenue", date_range={"start": "2022-06-01", "end": "2022-06-29"})

    sentence = template_sentence(plan, [{"value": 21390530.0, "orders": 35141}], PARTIAL)

    assert sentence.endswith("Jun 2022 has 29 of 30 days of data (missing 30 Jun).")


def test_an_all_time_total_gets_no_partial_month_wording() -> None:
    sentence = template_sentence(Plan(metric="orders"), [{"value": 120378, "orders": 120378}],
                                 PARTIAL)

    assert "day" not in sentence


def test_calling_a_one_day_march_low_is_replaced_by_the_template() -> None:
    answer = write_answer("monthly revenue trend", TREND, TREND_ROWS, True,
                          complete=Writer("Revenue peaked in Apr 2022 at ₹2,62,34,520, while "
                                          "March was only ₹94,810."), partial=PARTIAL)

    assert answer.source == "template"
    assert "only 1 day of data" in (answer.text or "")


def test_a_drop_into_june_must_mention_the_missing_day() -> None:
    sentence = "Revenue fell by ₹25,63,004 from May to June."

    assert numcheck.misleads_on_partial(sentence, PARTIAL)
    assert not numcheck.misleads_on_partial(
        "Revenue fell by ₹25,63,004 from May to June; June is missing 30 Jun, so part of this "
        "drop is the missing day.", PARTIAL)


def test_a_sentence_that_names_the_coverage_is_kept_and_its_day_numbers_pass() -> None:
    writer = Writer("April had the most revenue at ₹2,62,34,520. March has only 1 day of data "
                    "(31 Mar), so its ₹94,810 is not comparable.")

    answer = write_answer("monthly revenue trend", TREND, TREND_ROWS, True, complete=writer,
                          partial=PARTIAL)

    assert answer.source == "llm"
    assert '"partial_months": ["Mar 2022 has only 1 day of data (31 Mar)"' in writer.user


def test_the_writer_is_told_about_partial_months_only_when_they_are_in_the_answer() -> None:
    writer = Writer("There are 1,20,378 orders.")

    write_answer("how many orders", Plan(metric="orders"), [{"value": 120378, "orders": 120378}],
                 True, complete=writer, partial=PARTIAL)

    assert '"partial_months": []' in writer.user


def test_the_caveat_names_both_partial_months_on_a_monthly_trend() -> None:
    caveats = verify.caveats_for(TREND, TREND_ROWS, ["2022-03"], {}, PARTIAL)

    assert caveats[:2] == [
        "Mar 2022 is a partial month: only 1 day of data (31 Mar), so it is not comparable "
        "to full months.",
        "Jun 2022 is a partial month: 29 of 30 days of data (missing 30 Jun), so it is not "
        "comparable to full months.",
    ]
    assert verify.caveats_for(Plan(metric="revenue"), TREND_ROWS[:1], ["2022-03"], {},
                              PARTIAL) == []
