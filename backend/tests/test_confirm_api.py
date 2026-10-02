import csv
import io
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.sample import SAMPLE_ROLES
from tests.conftest import FIXTURES, use_key

GOLDEN = Path(__file__).resolve().parents[2] / "eval" / "golden.yaml"


def upload(client: TestClient, name: str) -> dict:
    content = (FIXTURES / name).read_bytes()
    return use_key(client, client.post("/api/datasets", files={"file": (name, content)}).json())


def suggested_roles(body: dict) -> dict[str, str | None]:
    return {r["role"]: r["column"] for r in body["roles"]}


def test_confirm_cleans_and_returns_the_data_check(client: TestClient, storage_root: Path) -> None:
    created = upload(client, "amazon_300.csv")

    response = client.post(f"/api/datasets/{created['dataset_id']}/confirm",
                           json={"roles": suggested_roles(created)})

    assert response.status_code == 200
    check = response.json()
    assert check["rows_in"] == 300
    assert check["rows_out"] == 300
    assert "profit and margin" in {i["topic"] for i in check["capability"]["cannot_answer"]}
    clean = pd.read_parquet(storage_root / created["dataset_id"] / "clean.parquet")
    assert list(clean.columns)[:4] == ["order_id", "order_date", "status_raw", "is_cancelled"]
    assert len(clean) == 300


def test_confirm_marks_roles_confirmed_in_metadata(client: TestClient) -> None:
    created = upload(client, "amazon_300.csv")
    client.post(f"/api/datasets/{created['dataset_id']}/confirm",
                json={"roles": suggested_roles(created)})

    stored = client.get(f"/api/datasets/{created['dataset_id']}").json()

    assert stored["roles_confirmed"] is True
    assert stored["data_check"]["rows_out"] == 300
    assert all(r["reasons"] == ["confirmed by the user"] for r in stored["roles"] if r["column"])


def test_user_can_fill_a_role_detection_left_blank(client: TestClient) -> None:
    created = upload(client, "shopify_orders.csv")
    roles = suggested_roles(created) | {"order_id": "Name"}

    response = client.post(f"/api/datasets/{created['dataset_id']}/confirm", json={"roles": roles})

    assert response.status_code == 200
    assert response.json()["rows_out"] == 40


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"order_id": None}, "order_id"),
        ({"amount": "Not A Column"}, "not in the file"),
        ({"qty": "Order ID"}, "more than one role"),
        ({"profit": "Amount"}, "Unknown role"),
    ],
)
def test_invalid_roles_return_400_with_a_reason(
    client: TestClient, change: dict, message: str
) -> None:
    created = upload(client, "amazon_300.csv")

    response = client.post(f"/api/datasets/{created['dataset_id']}/confirm",
                           json={"roles": suggested_roles(created) | change})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_roles"
    assert message in response.json()["error"]["message"]


def test_fixes_returns_the_fix_log_as_csv(client: TestClient) -> None:
    created = upload(client, "amazon_300.csv")
    client.post(f"/api/datasets/{created['dataset_id']}/confirm",
                json={"roles": suggested_roles(created)})

    response = client.get(f"/api/datasets/{created['dataset_id']}/fixes")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert {"rule", "column", "before", "after", "rows_affected"} == set(rows[0])
    assert any(r["rule"] == "state_normalised" and r["before"] == "MAHARASHTRA" for r in rows)


def test_fixes_before_confirm_returns_409(client: TestClient) -> None:
    created = upload(client, "amazon_300.csv")

    response = client.get(f"/api/datasets/{created['dataset_id']}/fixes")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_cleaned"


def test_latin1_upload_is_cleaned_from_its_utf8_copy(
    client: TestClient, storage_root: Path
) -> None:
    created = upload(client, "latin1.csv")

    client.post(f"/api/datasets/{created['dataset_id']}/confirm",
                json={"roles": suggested_roles(created)})

    clean = pd.read_parquet(storage_root / created["dataset_id"] / "clean.parquet")
    assert "Café Crème" in set(clean["category"])


def test_xlsx_upload_can_be_confirmed(client: TestClient) -> None:
    created = upload(client, "orders.xlsx")

    response = client.post(f"/api/datasets/{created['dataset_id']}/confirm",
                           json={"roles": suggested_roles(created)})

    assert response.status_code == 200
    assert response.json()["rows_out"] == 20


def test_sample_comes_with_its_data_check(client: TestClient) -> None:
    body = client.post("/api/datasets/sample").json()

    assert body["data_check"]["rows_out"] == 300
    confirm = client.post(f"/api/datasets/{body['dataset_id']}/confirm", json={"roles": {}})
    assert confirm.json() == body["data_check"]
    assert client.get(f"/api/datasets/{body['dataset_id']}/fixes").status_code == 200


@pytest.fixture(scope="module")
def cleaned_sample(real_sample_cache: Path) -> tuple[pd.DataFrame, dict]:
    metadata = json.loads((real_sample_cache / "metadata.json").read_text(encoding="utf-8"))
    return pd.read_parquet(real_sample_cache / "clean.parquet"), metadata


def golden(anchor_id: str) -> object:
    anchors = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))["anchors"]
    return next(a["expected"] for a in anchors if a["id"] == anchor_id)


def test_cleaned_sample_keeps_every_row(cleaned_sample: tuple[pd.DataFrame, dict]) -> None:
    clean, dataset = cleaned_sample

    assert len(clean) == 128975
    assert dataset["data_check"]["rows_in"] == 128975
    assert dataset["data_check"]["partial_months"] == ["2022-03"]
    assert dataset["data_check"]["unknown_states"] == ["APO"]


def test_cleaned_sample_matches_the_answer_key_counts(
    cleaned_sample: tuple[pd.DataFrame, dict],
) -> None:
    clean, _ = cleaned_sample
    orders_by_state = clean.groupby("state")["order_id"].nunique()

    assert clean["order_id"].nunique() == golden("total_orders")
    assert orders_by_state["Rajasthan"] == golden("rajasthan_orders")
    top = orders_by_state.sort_values(ascending=False).head(1)
    assert {str(top.index[0]): int(top.iloc[0])} == golden("top_state_by_orders")
    assert clean["state"].nunique() == 37
    assert set(SAMPLE_ROLES) <= {"order_id", "order_date", "amount", "status", "state", "city",
                                 "category", "sku", "fulfilment", "qty", "channel"}


def test_data_check_reports_the_date_range_and_order_count(real_sample_cache: Path) -> None:
    check = json.loads((real_sample_cache / "metadata.json").read_text("utf-8"))["data_check"]

    assert (check["date_min"], check["date_max"]) == ("2022-03-31", "2022-06-29")
    assert check["orders"] == 120378
