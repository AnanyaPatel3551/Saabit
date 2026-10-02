"""Evidence shown with every answer: the comparison value, the plain-words explanation and the
first source rows. All numbers come from the pipeline (both engines), never from the LLM."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.datasets import get_storage_root
from app.api.sample import get_sample_cache_dir
from app.core.templates import format_count
from app.main import create_app

RAJASTHAN = {"status": "ok", "metric": "cancellation_rate",
             "filters": [{"column": "state", "op": "eq", "values": ["rajasthan"]}]}


@pytest.fixture
def real(tmp_path: Path, real_sample_cache: Path) -> tuple[TestClient, str]:
    app = create_app(frontend_dist=tmp_path / "no-frontend")
    app.dependency_overrides[get_storage_root] = lambda: tmp_path / "storage"
    app.dependency_overrides[get_sample_cache_dir] = lambda: real_sample_cache
    client = TestClient(app)
    return client, client.post("/api/datasets/sample").json()["dataset_id"]


def run(real: tuple[TestClient, str], plan: dict) -> dict:
    client, dataset = real
    return client.post(f"/api/datasets/{dataset}/run", json=plan).json()


def test_a_filtered_single_number_comes_with_the_all_orders_value(real) -> None:
    body = run(real, RAJASTHAN)

    assert body["card"]["result"][0]["value"] == pytest.approx(14.2118, abs=0.01)
    comparison = body["comparison"]
    assert comparison["label"] == "all orders"
    assert comparison["value"] == pytest.approx(14.2759, abs=0.01)  # golden anchor
    assert comparison["verified"] is True and comparison["card_id"]


def test_no_comparison_for_unfiltered_or_grouped_answers(real) -> None:
    assert run(real, {"status": "ok", "metric": "revenue"})["comparison"] is None
    grouped = {"status": "ok", "metric": "orders", "group_by": ["fulfilment"]}
    assert run(real, grouped)["comparison"] is None


def test_explanation_says_how_the_number_was_calculated(real) -> None:
    body = run(real, RAJASTHAN)
    text = " ".join(body["explanation"])

    assert "Distinct cancelled orders divided by distinct orders, times 100." in text
    assert "State is Rajasthan" in text
    assert "RJ" in text and "Rajsthan" in text  # merged spellings, from the fix log
    assert "31 Mar 2022 to 29 Jun 2022" in text
    assert f"{format_count(body['card']['row_count'])} source rows" in text


def test_explanation_names_the_chosen_period(real) -> None:
    plan = {"status": "ok", "metric": "revenue",
            "date_range": {"start": "2022-05-01", "end": "2022-05-31"}}

    assert any("1 May 2022 to 31 May 2022" in line for line in run(real, plan)["explanation"])


def test_first_five_source_rows_come_with_the_answer(real) -> None:
    body = run(real, RAJASTHAN)

    rows = body["rows_preview"]
    assert 1 <= len(rows) <= 5
    assert {"order_id", "order_date", "state"} <= set(rows[0])
    assert all(row["state"] == "Rajasthan" for row in rows)
