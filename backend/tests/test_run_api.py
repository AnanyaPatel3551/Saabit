import csv
import io
from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import FIXTURES


def sample(client: TestClient) -> str:
    return client.post("/api/datasets/sample").json()["dataset_id"]


def run(client: TestClient, dataset_id: str, plan: dict):
    return client.post(f"/api/datasets/{dataset_id}/run", json=plan)


def test_run_returns_verified_card_and_a_sentence(
    client: TestClient, storage_root: Path
) -> None:
    dataset_id = sample(client)

    response = run(client, dataset_id, {"metric": "orders", "group_by": ["fulfilment"]})

    assert response.status_code == 200
    body = response.json()
    assert body["verified"] is True
    assert body["sentence"] == "Orders by fulfilment: Amazon 222, Merchant 64."
    assert body["source"] == "template"  # no key in tests, so the template is used
    card = body["card"]
    assert card["sql"].startswith("SELECT")
    assert "groupby" in card["pandas_code"]
    assert card["row_count"] == 300
    assert (storage_root / dataset_id / "cards" / f"{card['card_id']}.json").is_file()


def test_rows_are_paginated_as_json(client: TestClient) -> None:
    card = run(client, sample(client), {"metric": "orders"}).json()["card"]

    first = client.get(f"/api/cards/{card['card_id']}/rows?page=1").json()
    third = client.get(f"/api/cards/{card['card_id']}/rows?page=3").json()

    assert (first["page_size"], first["total_rows"], first["pages"]) == (100, 300, 3)
    assert len(first["rows"]) == 100
    assert len(third["rows"]) == 100
    assert first["rows"][0]["order_id"] != third["rows"][0]["order_id"]


def test_rows_download_as_csv_matches_the_filter(client: TestClient) -> None:
    card = run(client, sample(client), {
        "metric": "orders", "filters": [{"column": "state", "values": ["Karnataka"]}],
    }).json()["card"]

    response = client.get(f"/api/cards/{card['card_id']}/rows?format=csv")

    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == card["row_count"] > 0
    assert {r["state"] for r in rows} == {"Karnataka"}


def test_unknown_card_returns_404(client: TestClient) -> None:
    dataset_id = sample(client)

    missing = client.get(f"/api/cards/{dataset_id}-00000000/rows")
    malformed = client.get("/api/cards/not-a-card/rows")

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "card_not_found"
    assert malformed.status_code == 404


def test_run_on_an_unconfirmed_upload_returns_409(client: TestClient) -> None:
    content = (FIXTURES / "amazon_300.csv").read_bytes()
    dataset_id = client.post("/api/datasets", files={"file": ("a.csv", content)}).json()[
        "dataset_id"]

    response = run(client, dataset_id, {"metric": "orders"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_cleaned"


def test_run_works_on_a_confirmed_upload(client: TestClient) -> None:
    content = (FIXTURES / "amazon_300.csv").read_bytes()
    created = client.post("/api/datasets", files={"file": ("a.csv", content)}).json()
    roles = {r["role"]: r["column"] for r in created["roles"]}
    client.post(f"/api/datasets/{created['dataset_id']}/confirm", json={"roles": roles})

    response = run(client, created["dataset_id"], {"metric": "revenue", "group_by": ["state"],
                                                   "sort": {"by": "value", "dir": "desc"},
                                                   "limit": 3})

    assert response.status_code == 200
    assert response.json()["verified"] is True
    assert len(response.json()["card"]["result"]) == 3


def test_invalid_plan_returns_400_with_code(client: TestClient) -> None:
    response = run(client, sample(client), {"metric": "profit"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_plan"


def test_unknown_filter_value_returns_400_with_options(client: TestClient) -> None:
    response = run(client, sample(client), {
        "metric": "orders", "filters": [{"column": "state", "values": ["Keralaa"]}],
    })

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "unknown_filter_value"
    assert "Kerala" in error["message"]


def test_plan_with_unknown_field_is_rejected(client: TestClient) -> None:
    response = run(client, sample(client), {"metric": "orders", "sql": "DROP TABLE clean"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
