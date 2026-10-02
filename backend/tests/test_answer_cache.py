"""Asking the same question again serves the finished answer from disk: nothing recomputed.

Only verified answers are cached; re-confirming the columns starts afresh; the cache lives in
the dataset's own folder, so deleting the dataset deletes it.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import answer_cache, pipeline, verify
from tests.conftest import FIXTURES, use_key

TREND = {"metric": "revenue", "group_by": ["month"], "sort": {"by": "key", "dir": "asc"}}


def confirmed_upload(client: TestClient) -> dict:
    files = {"file": ("orders.csv", (FIXTURES / "amazon_300.csv").read_bytes(), "text/csv")}
    created = use_key(client, client.post("/api/datasets", files=files).json())
    roles = {r["role"]: r["column"] for r in created["roles"]}
    assert client.post(f"/api/datasets/{created['dataset_id']}/confirm",
                       json={"roles": roles}).status_code == 200
    return {**created, "confirmed_roles": roles}


def test_the_same_question_again_is_served_from_the_cache(
        client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset = confirmed_upload(client)
    first = client.post(f"/api/datasets/{dataset['dataset_id']}/run", json=TREND).json()
    runs: list[str] = []
    real = pipeline.run_plan
    monkeypatch.setattr(pipeline, "run_plan", lambda *a, **k: runs.append("ran") or real(*a, **k))

    again = client.post(f"/api/datasets/{dataset['dataset_id']}/run", json=TREND).json()

    assert first["cached"] is False
    assert again["cached"] is True
    assert runs == []
    assert again["card"] == first["card"]
    assert again["card"]["result"] == first["card"]["result"]


def test_the_cache_is_kept_inside_the_datasets_own_folder(
        client: TestClient, storage_root: Path) -> None:
    dataset = confirmed_upload(client)
    client.post(f"/api/datasets/{dataset['dataset_id']}/run", json=TREND)

    entries = list((storage_root / dataset["dataset_id"] / "answers").glob("*.json"))

    assert len(entries) == 1
    client.delete(f"/api/datasets/{dataset['dataset_id']}")
    assert not (storage_root / dataset["dataset_id"]).exists()


def test_reconfirming_the_columns_misses_the_cache(client: TestClient) -> None:
    dataset = confirmed_upload(client)
    url = f"/api/datasets/{dataset['dataset_id']}"
    client.post(f"{url}/run", json={"metric": "orders"})
    roles = {**dataset["confirmed_roles"], "city": None}

    assert client.post(f"{url}/confirm", json={"roles": roles}).status_code == 200
    again = client.post(f"{url}/run", json={"metric": "orders"}).json()

    assert again["cached"] is False


def test_an_answer_the_two_engines_disagree_on_is_never_cached(
        client: TestClient, monkeypatch: pytest.MonkeyPatch, storage_root: Path) -> None:
    dataset = confirmed_upload(client)
    real = verify.compare

    def disagree(*args, **kwargs):  # type: ignore[no-untyped-def]
        return replace(real(*args, **kwargs), verified=False, mismatches=["value differs"])

    monkeypatch.setattr(verify, "compare", disagree)
    url = f"/api/datasets/{dataset['dataset_id']}/run"

    first = client.post(url, json={"metric": "orders"}).json()
    again = client.post(url, json={"metric": "orders"}).json()

    assert first["verified"] is False and again["cached"] is False
    assert not list((storage_root / dataset["dataset_id"] / "answers").glob("*.json"))


def test_a_refused_plan_is_never_cached(client: TestClient, storage_root: Path) -> None:
    dataset = confirmed_upload(client)
    url = f"/api/datasets/{dataset['dataset_id']}/run"

    response = client.post(url, json={"metric": "revenue", "group_by": ["colour"]})

    assert response.status_code >= 400
    assert not (storage_root / dataset["dataset_id"] / "answers").exists()


def test_a_written_sentence_is_reused_for_the_same_cached_answer(
        client: TestClient, monkeypatch: pytest.MonkeyPatch, storage_root: Path) -> None:
    from app.core import narrate

    dataset = confirmed_upload(client)
    card_id = client.post(f"/api/datasets/{dataset['dataset_id']}/run",
                          json=TREND).json()["card"]["card_id"]
    folder = storage_root / dataset["dataset_id"]
    answer_cache.write_sentence(folder, card_id, {"sentence": "Written once.", "source": "llm",
                                                  "note": None})
    monkeypatch.setattr(narrate, "write_answer", lambda *a, **k: pytest.fail("AI called again"))

    body = client.post(f"/api/cards/{card_id}/sentence", json={"question": "trend"}).json()

    assert body == {"sentence": "Written once.", "source": "llm", "note": None}


def test_each_dataset_keeps_at_most_200_answers(tmp_path: Path) -> None:
    for i in range(answer_cache.MAX_ENTRIES + 5):
        answer_cache.write(tmp_path, f"k{i:04d}", {"verified": True, "card": {"card_id": "x"}})

    assert len(list((tmp_path / "answers").glob("*.json"))) == answer_cache.MAX_ENTRIES
    assert json.loads((tmp_path / "answers" / "k0204.json").read_text())["verified"] is True
