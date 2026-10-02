"""Month coverage: a month is partial when the data misses its first or its last day."""

from datetime import date

from app.core.coverage import month_coverage, partial_coverage


def test_a_month_cut_short_at_the_start_edge_is_partial() -> None:
    months = month_coverage(date(2022, 3, 31), date(2022, 4, 30))

    march, april = months
    assert (march.month, march.partial, march.days, march.of) == ("2022-03", True, 1, 31)
    assert (april.partial, april.days, april.of) == (False, 30, 30)
    assert march.short_note() == "only 1 day"
    assert march.sentence_note() == "only 1 day of data (31 Mar)"


def test_a_month_cut_short_at_the_end_edge_is_partial() -> None:
    june = month_coverage(date(2022, 6, 1), date(2022, 6, 29))[0]

    assert (june.month, june.partial, june.days, june.of) == ("2022-06", True, 29, 30)
    assert june.short_note() == "29 of 30 days"
    assert june.sentence_note() == "29 of 30 days of data (missing 30 Jun)"


def test_the_sample_range_has_march_and_june_partial_and_april_may_full() -> None:
    partial = partial_coverage(date(2022, 3, 31), date(2022, 6, 29))

    assert sorted(partial) == ["2022-03", "2022-06"]
    assert [c.days for c in month_coverage(date(2022, 3, 31), date(2022, 6, 29))] == [1, 30, 31, 29]


def test_a_single_month_missing_both_edges_names_both_gaps() -> None:
    only = month_coverage(date(2022, 5, 3), date(2022, 5, 30))[0]

    assert only.days == 28
    assert only.sentence_note() == "28 of 31 days of data (missing 1 May to 2 May and 31 May)"


def test_full_months_and_february_in_a_leap_year_are_not_partial() -> None:
    assert partial_coverage(date(2024, 1, 1), date(2024, 2, 29)) == {}
    assert month_coverage(None, date(2024, 1, 1)) == []
