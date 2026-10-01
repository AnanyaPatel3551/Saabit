"""The eval rubric, checked on its own (no app, no LLM)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scoring  # noqa: E402


def test_a_count_must_match_exactly():
    assert scoring.match_value(35141, 35141, 0)
    assert not scoring.match_value(35140, 35141, 0)


def test_money_is_correct_within_one_paisa():
    assert scoring.match_value(23953534.004, 23953534.00, 0.01)
    assert not scoring.match_value(23953534.02, 23953534.00, 0.01)


def test_a_missing_value_is_never_correct():
    assert not scoring.match_value(None, 0, 0.01)


def test_unordered_rows_match_on_keys_regardless_of_case_and_order():
    got = [{"fulfilment": "merchant", "value": 36376}, {"fulfilment": "Amazon", "value": 84002}]
    assert scoring.match_rows(got, {"Amazon": 84002, "Merchant": 36376}, 0, ordered=False)


def test_unordered_rows_fail_when_a_group_is_extra_or_missing():
    got = [{"k": "Amazon", "value": 1}, {"k": "Merchant", "value": 2}, {"k": "Other", "value": 3}]
    assert not scoring.match_rows(got, {"Amazon": 1, "Merchant": 2}, 0, ordered=False)


def test_top_n_rows_must_come_in_the_expected_order():
    expected = {"Maharashtra": 20780, "Karnataka": 16182}
    right = [{"state": "Maharashtra", "value": 20780}, {"state": "Karnataka", "value": 16182}]
    swapped = list(reversed(right))
    assert scoring.match_rows(right, expected, 0, ordered=True)
    assert not scoring.match_rows(swapped, expected, 0, ordered=True)


def test_rows_fail_when_one_value_is_outside_tolerance():
    got = [{"m": "2022-04", "value": 14.6670}, {"m": "2022-05", "value": 13.9950}]
    expected = {"2022-04": 14.6670, "2022-05": 13.9823}
    assert not scoring.match_rows(got, expected, 0.01, ordered=False)


def test_refusal_needs_unsupported_status_and_a_reason_word():
    assert scoring.match_refusal("unsupported", "The file has no cost column.", ["cost"])
    assert not scoring.match_refusal("ok", "no cost column", ["cost"])
    assert not scoring.match_refusal("unsupported", "Cannot answer that.", ["cost"])


def test_refusal_words_match_whole_words_only():
    assert not scoring.match_refusal("unsupported", "The file is broad.", ["ad"])
    assert scoring.match_refusal("unsupported", "There is no ad spend column.", ["ad"])


def test_caveat_is_found_case_insensitively():
    assert scoring.has_caveat(["March 2022 is a Partial month."], "partial")
    assert not scoring.has_caveat([], "partial")
    assert scoring.has_caveat([], None)


def test_indian_numbers_are_parsed_from_answer_text():
    assert scoring.parse_number("₹2,39,53,534") == 23953534
    assert scoring.parse_number("14.2%") == 14.2
    assert scoring.parse_number("about 2.40 Cr") == 24000000
    assert scoring.parse_number("1.5 lakh orders") == 150000
    assert scoring.parse_number("no number here") is None


def test_grouped_answer_text_is_parsed_into_rows():
    rows = scoring.parse_rows("Amazon=12.86%; Merchant = 17.54%")
    assert rows == [{"key": "Amazon", "value": 12.86}, {"key": "Merchant", "value": 17.54}]


def test_percentiles_use_the_nearest_rank():
    assert scoring.percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.0
    assert scoring.percentile([1.0, 2.0, 3.0, 4.0], 95) == 4.0
    assert scoring.percentile([], 50) is None
