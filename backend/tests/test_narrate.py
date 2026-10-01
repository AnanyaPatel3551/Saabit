import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cli import main as cli_main
from app.core.narrate import MAX_TABLE_ROWS, write_answer
from app.core.plan import Plan
from app.llm import client as llm
from app.llm.client import LLMUnavailable, ModelOutputError

PLAN = Plan(metric="revenue", date_range={"start": "2022-05-01", "end": "2022-05-31"})
ROWS = [{"value": 23953534.0, "orders": 39221}]
QUESTION = "revenue in may 2022"


class FakeWriter:
    def __init__(self, reply: object) -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply  # type: ignore[return-value]


def test_checked_llm_sentence_is_used() -> None:
    writer = FakeWriter({"sentence": "Revenue in May 2022 was ₹2.40 Cr across 39,221 orders."})

    answer = write_answer(QUESTION, PLAN, ROWS, verified=True, complete=writer)

    assert answer.source == "llm"
    assert answer.text == "Revenue in May 2022 was ₹2.40 Cr across 39,221 orders."
    assert answer.unmatched == []


def test_hallucinated_number_falls_back_to_template() -> None:
    writer = FakeWriter({"sentence": "Revenue in May 2022 was ₹2.40 Cr, 12% higher than April."})

    answer = write_answer(QUESTION, PLAN, ROWS, verified=True, complete=writer)

    assert answer.source == "template"
    assert answer.unmatched == ["12%"]
    assert answer.rejected == "Revenue in May 2022 was ₹2.40 Cr, 12% higher than April."
    assert "₹2,39,53,534" in answer.text


def test_more_than_two_sentences_falls_back_to_template() -> None:
    writer = FakeWriter({"sentence": "Revenue was ₹2.40 Cr. It was May. Orders were 39,221."})

    assert write_answer(QUESTION, PLAN, ROWS, True, complete=writer).source == "template"


def test_decimal_points_do_not_count_as_sentence_ends() -> None:
    writer = FakeWriter({"sentence": "Revenue was ₹2.40 Cr. Orders were 39,221."})

    assert write_answer(QUESTION, PLAN, ROWS, True, complete=writer).source == "llm"


@pytest.mark.parametrize("failure", [LLMUnavailable("timeout", "no reply within 15 s"),
                                     ModelOutputError("the reply was not valid JSON")])
def test_llm_down_uses_template(failure: Exception) -> None:
    answer = write_answer(QUESTION, PLAN, ROWS, verified=True, complete=FakeWriter(failure))

    assert answer.source == "template"
    assert answer.text.startswith("Revenue")


def test_reply_without_a_sentence_uses_template() -> None:
    answer = write_answer(QUESTION, PLAN, ROWS, True, complete=FakeWriter({"answer": "x"}))

    assert answer.source == "template"


def test_unverified_result_gets_no_sentence() -> None:
    writer = FakeWriter({"sentence": "should never be asked"})
    sql = [{"value": 23953534.0, "orders": 39221}]
    pandas = [{"value": 24193069.34, "orders": 39221}]

    answer = write_answer(QUESTION, PLAN, [], verified=False, sql_rows=sql, pandas_rows=pandas,
                          complete=writer)

    assert answer.text is None
    assert answer.source == "unverified"
    assert "Could not verify" in answer.note
    assert "₹2,39,53,534" in answer.note and "₹2,41,93,069" in answer.note
    assert writer.calls == []


def test_writer_sees_at_most_20_rows_and_no_raw_lines() -> None:
    plan = Plan(metric="orders", group_by=["sku"])
    rows = [{"sku": f"SKU-{i}", "value": float(100 - i), "orders": 100 - i} for i in range(60)]
    writer = FakeWriter({"sentence": "SKU-0 has the most orders."})

    write_answer("orders by sku", plan, rows, True, complete=writer)

    table = json.loads(writer.calls[0][1])["rows"]
    assert len(table) == MAX_TABLE_ROWS
    assert "first 20 of 60 rows" in writer.calls[0][1]


def sample_id(cache: Path) -> str:
    return json.loads((cache / "metadata.json").read_text("utf-8"))["dataset_id"]


def answer(client: TestClient, question: str = "how many orders") -> tuple[dict, dict]:
    """/run (numbers first), then the sentence for its card."""
    dataset_id = client.post("/api/datasets/sample").json()["dataset_id"]
    run = client.post(f"/api/datasets/{dataset_id}/run", json={"metric": "orders"}).json()
    sentence = client.post(f"/api/cards/{run['card']['card_id']}/sentence",
                           json={"question": question}).json()
    return run, sentence


def test_sentence_endpoint_returns_the_checked_llm_sentence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm, "complete_json",
                        FakeWriter({"sentence": "There were 286 orders."}))

    run, sentence = answer(client)

    assert (run["sentence"], run["source"], run["sentence_status"]) == (
        "There are 286 orders.", "template", "pending")
    assert (sentence["sentence"], sentence["source"], sentence["note"]) == (
        "There were 286 orders.", "llm", None)


def test_sentence_endpoint_replaces_a_wrong_llm_number_with_the_template(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The 300-line fixture has 286 distinct orders; "300" is a plausible but wrong claim.
    monkeypatch.setattr(llm, "complete_json",
                        FakeWriter({"sentence": "There were 300 orders."}))

    _, sentence = answer(client)

    assert (sentence["sentence"], sentence["source"]) == ("There are 286 orders.", "template")


def test_without_llm_both_steps_answer_with_the_template(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llm, "complete_json",
                        FakeWriter(LLMUnavailable("not_configured", "GROQ_API_KEY is not set")))

    run, sentence = answer(client)

    assert run["sentence"] == sentence["sentence"] == "There are 286 orders."
    assert sentence["source"] == "template"


def test_cli_fake_answer_shows_the_check(
    sample_cache: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SAABIT_SAMPLE_CACHE", str(sample_cache))
    monkeypatch.setenv("SAABIT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr("app.cli.make_plan", lambda *a, **k: type("R", (), {
        "plan": Plan(metric="orders"), "caveats": [], "cached": False})())

    code = cli_main(["ask", "how many orders", "--fake-answer", "There were 999 orders."])

    out = capsys.readouterr().out
    assert code == 0
    assert "unmatched: ['999']" in out
    assert "--- answer (template)" in out
