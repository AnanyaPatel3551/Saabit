"""Numbers first: /run answers without the LLM; the sentence comes from its own endpoint."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import evidence, narrate
from tests.test_hardening import make_client


def run_orders(client: TestClient) -> dict:
    dataset_id = client.post("/api/datasets/sample").json()["dataset_id"]
    return client.post(f"/api/datasets/{dataset_id}/run",
                       json={"metric": "orders", "group_by": ["fulfilment"]}).json()


def test_run_returns_numbers_without_calling_the_writer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_writer(*_: object, **__: object) -> None:
        raise AssertionError("/run must not call the answer writer")

    monkeypatch.setattr(narrate, "write_answer", no_writer)

    body = run_orders(client)

    assert body["verified"] is True and body["sentence_status"] == "pending"
    assert body["source"] == "template" and body["sentence"]
    assert body["card"]["result"]  # the chart data and evidence come back at once


def test_run_no_longer_takes_the_question_in_the_url(client: TestClient) -> None:
    dataset_id = client.post("/api/datasets/sample").json()["dataset_id"]

    response = client.post(f"/api/datasets/{dataset_id}/run?question=secret",
                           json={"metric": "orders"})

    assert response.status_code == 200  # an old client still works; the parameter is ignored


def test_unverified_card_gets_no_sentence_and_no_llm_call(
    client: TestClient, storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = run_orders(client)["card"]
    card = evidence.load_card(storage_root / saved["dataset_id"] / "cards", saved["card_id"])
    card.verified = False
    card.sql_result = [{"fulfilment": "Amazon", "value": 1.0, "orders": 1}]
    card.pandas_result = [{"fulfilment": "Amazon", "value": 2.0, "orders": 2}]
    evidence.save_card(storage_root / card.dataset_id / "cards", card)
    monkeypatch.setattr("app.llm.client.complete_json",
                        lambda *_: (_ for _ in ()).throw(AssertionError("no LLM call")))

    body = client.post(f"/api/cards/{card.card_id}/sentence", json={"question": ""}).json()

    assert body["sentence"] is None and body["source"] == "unverified"
    assert "Could not verify" in body["note"]


def test_unknown_card_gets_404(client: TestClient) -> None:
    response = client.post("/api/cards/0123456789ab-deadbeef/sentence", json={"question": ""})

    assert response.status_code == 404


def test_the_31st_sentence_in_10_minutes_gets_429(tmp_path: Path, storage_root: Path,
                                                   sample_cache: Path) -> None:
    client = make_client(tmp_path, storage_root, sample_cache)
    card_id = run_orders(client)["card"]["card_id"]

    statuses = [client.post(f"/api/cards/{card_id}/sentence", json={"question": ""})
                .status_code for _ in range(31)]

    assert statuses[:30] == [200] * 30 and statuses[30] == 429
