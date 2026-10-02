"""The same question gives the same answer text: one amount style decided by code, fixed
sentence shapes, temperature 0, and the shown sentence cached for repeats."""

import pytest
from fastapi.testclient import TestClient

from app.core import numcheck
from app.core.narrate import formatted_rows, write_answer
from app.core.plan import Plan
from app.core.templates import display_inr, template_sentence
from app.llm.client import SEED, request_body
from app.llm.config import LLMConfig
from tests.conftest import FIXTURES, use_key

TOP5 = Plan(metric="revenue", group_by=["state"], sort={"by": "value", "dir": "desc"}, limit=5)
TOP5_ROWS = [
    {"state": "Maharashtra", "value": 12224770.0, "orders": 20780},
    {"state": "Karnataka", "value": 9649981.0, "orders": 16182},
    {"state": "Telangana", "value": 6916615.65, "orders": 10405},
    {"state": "Uttar Pradesh", "value": 6816642.08, "orders": 10062},
    {"state": "Tamil Nadu", "value": 6515650.11, "orders": 10519},
]


class Writer:
    def __init__(self, sentence: str) -> None:
        self.sentence = sentence
        self.users: list[str] = []

    def __call__(self, system: str, user: str) -> dict:
        self.users.append(user)
        return {"sentence": self.sentence}


@pytest.mark.parametrize(("value", "expected"), [
    (94810, "₹94,810"),
    (9649981, "₹96.50 lakh"),
    (12224770, "₹1.22 Cr"),
    (2.5e9, "₹250.00 Cr"),
    (0, "₹0"),
    (-12224770, "-₹1.22 Cr"),
    (694.56, "₹694.56"),
])
def test_amounts_in_sentences_have_one_style(value: float, expected: str) -> None:
    assert display_inr(value) == expected


def test_the_ranking_template_has_the_fixed_shape() -> None:
    assert template_sentence(TOP5, TOP5_ROWS) == (
        "Maharashtra leads in revenue with ₹1.22 Cr, followed by Karnataka (₹96.50 lakh), "
        "Telangana (₹69.17 lakh), Uttar Pradesh (₹68.17 lakh) and Tamil Nadu (₹65.16 lakh).")


def test_the_writer_sees_display_strings_only_never_raw_numbers() -> None:
    rows = formatted_rows(TOP5, TOP5_ROWS)

    assert rows[0] == {"state": "Maharashtra", "value": "₹1.22 Cr", "orders": "20,780"}
    assert all(isinstance(v, str) for row in rows for v in row.values())


def test_a_reformatted_amount_is_rejected_and_the_template_is_used() -> None:
    sentence = ("Maharashtra leads in revenue with ₹1,22,24,770, followed by Karnataka "
                "(₹96,49,981).")

    assert numcheck.off_style_amounts(sentence) == ["₹1,22,24,770", "₹96,49,981"]
    answer = write_answer("Top 5 states by revenue", TOP5, TOP5_ROWS, True,
                          complete=Writer(sentence))
    assert answer.source == "template"
    assert answer.text == template_sentence(TOP5, TOP5_ROWS)


def test_amounts_copied_as_given_pass() -> None:
    sentence = template_sentence(TOP5, TOP5_ROWS)

    assert numcheck.off_style_amounts(sentence) == []
    answer = write_answer("Top 5 states by revenue", TOP5, TOP5_ROWS, True,
                          complete=Writer(sentence))
    assert answer.source == "llm"


def test_asking_twice_with_a_fixed_writer_gives_identical_text() -> None:
    writer = Writer("Maharashtra leads in revenue with ₹1.22 Cr, followed by Karnataka "
                    "(₹96.50 lakh).")

    first = write_answer("Top 5 states by revenue", TOP5, TOP5_ROWS, True, complete=writer)
    second = write_answer("Top 5 states by revenue", TOP5, TOP5_ROWS, True, complete=writer)

    assert first.text == second.text
    assert writer.users[0] == writer.users[1]  # the same input both times


@pytest.mark.parametrize("provider", ["groq", "nim"])
def test_every_ai_call_uses_temperature_0(provider: str) -> None:
    config = LLMConfig(name=provider, model="m", api_key="k", base_url="https://example.test")

    body = request_body(config, "system", "user")

    assert body["temperature"] == 0
    if provider == "groq":
        assert body["seed"] == SEED


def test_a_repeated_question_returns_the_same_sentence_byte_for_byte(client: TestClient) -> None:
    files = {"file": ("orders.csv", (FIXTURES / "amazon_300.csv").read_bytes(), "text/csv")}
    created = use_key(client, client.post("/api/datasets", files=files).json())
    roles = {r["role"]: r["column"] for r in created["roles"]}
    url = f"/api/datasets/{created['dataset_id']}"
    client.post(f"{url}/confirm", json={"roles": roles})
    plan = TOP5.model_dump(mode="json")

    first = client.post(f"{url}/run", json=plan).json()
    shown = client.post(f"/api/cards/{first['card']['card_id']}/sentence",
                        json={"question": "Top 5 states by revenue"}).json()
    repeats = [client.post(f"{url}/run", json=plan).json() for _ in range(2)]

    for again in repeats:
        assert again["cached"] is True
        assert again["sentence_status"] == "final"
        assert again["sentence"].encode() == shown["sentence"].encode()
