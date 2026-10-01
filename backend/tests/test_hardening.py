"""Phase 10a hardening: rate limits, the catch-all error, request logs, security headers,
upload safety, retention, the fallback timeout and health. No network, no real LLM.
"""

import json
import logging
import os
import re
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import openpyxl
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.datasets import get_sample_path, get_storage_root
from app.api.ratelimit import QUESTIONS, UPLOADS, RateLimiter, client_ip
from app.api.sample import get_sample_cache_dir
from app.core import ingest, retention
from app.llm import client as llm
from app.llm import config
from app.main import create_app
from tests.conftest import FIXTURES, SMALL_SAMPLE

ORDER_ID = re.compile(r"\d{3}-\d{7}-\d{7}")


def make_client(tmp_path: Path, storage_root: Path, sample_cache: Path,
                client: tuple[str, int] = ("testclient", 50000)) -> TestClient:
    app = create_app(frontend_dist=tmp_path / "no-frontend")
    app.dependency_overrides[get_storage_root] = lambda: storage_root
    app.dependency_overrides[get_sample_path] = lambda: SMALL_SAMPLE
    app.dependency_overrides[get_sample_cache_dir] = lambda: sample_cache
    return TestClient(app, client=client, raise_server_exceptions=False)


def sample_id(client: TestClient) -> str:
    return client.post("/api/datasets/sample").json()["dataset_id"]


def small_csv() -> bytes:
    return (FIXTURES / "amazon_300.csv").read_bytes()


# --- 1. rate limits ----------------------------------------------------------------------

def test_the_31st_question_in_10_minutes_gets_429_with_retry_after(
    tmp_path: Path, storage_root: Path, sample_cache: Path
) -> None:
    client = make_client(tmp_path, storage_root, sample_cache)
    dataset = sample_id(client)

    statuses = [client.post(f"/api/datasets/{dataset}/plan", json={"question": "orders"})
                .status_code for _ in range(30)]
    limited = client.post(f"/api/datasets/{dataset}/plan", json={"question": "orders"})

    assert 429 not in statuses  # without a key these are 503s, but each one counted
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert "30 every 10 minutes" in limited.json()["error"]["message"]
    assert 1 <= int(limited.headers["Retry-After"]) <= 600


def test_the_6th_upload_in_an_hour_gets_429(tmp_path: Path, storage_root: Path,
                                            sample_cache: Path) -> None:
    client = make_client(tmp_path, storage_root, sample_cache)
    files = {"file": ("orders.csv", small_csv(), "text/csv")}

    statuses = [client.post("/api/datasets", files=files).status_code for _ in range(6)]

    assert statuses == [200] * 5 + [429]


def test_a_slot_frees_up_when_the_oldest_request_leaves_the_window() -> None:
    now = [1000.0]
    limiter = RateLimiter(clock=lambda: now[0])
    for _ in range(UPLOADS.max_requests):
        limiter.check(UPLOADS, "1.2.3.4")
        now[0] += 10

    with pytest.raises(Exception) as error:
        limiter.check(UPLOADS, "1.2.3.4")
    assert error.value.retry_after == 3600 - 50  # type: ignore[attr-defined]

    now[0] = 1000.0 + 3600
    limiter.check(UPLOADS, "1.2.3.4")  # the first request has left the window


def test_limits_are_per_client_and_per_kind() -> None:
    limiter = RateLimiter(clock=lambda: 0.0)
    for _ in range(QUESTIONS.max_requests):
        limiter.check(QUESTIONS, "1.1.1.1")

    limiter.check(QUESTIONS, "2.2.2.2")
    limiter.check(UPLOADS, "1.1.1.1")


def request_from(peer: str, forwarded: str | None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


def test_behind_the_proxy_the_first_forwarded_address_is_the_client() -> None:
    assert client_ip(request_from("10.1.2.3", "203.0.113.7, 10.1.2.3")) == "203.0.113.7"


def test_a_direct_client_cannot_choose_its_address_with_the_header() -> None:
    assert client_ip(request_from("198.51.100.9", "203.0.113.7")) == "198.51.100.9"


def test_without_the_header_the_socket_address_is_used() -> None:
    assert client_ip(request_from("10.1.2.3", None)) == "10.1.2.3"


def test_trusted_proxies_can_be_set_by_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAABIT_TRUSTED_PROXIES", "198.51.100.0/24")

    assert client_ip(request_from("198.51.100.9", "203.0.113.7")) == "203.0.113.7"
    assert client_ip(request_from("10.1.2.3", "203.0.113.7")) == "10.1.2.3"


def test_via_the_proxy_each_forwarded_client_has_its_own_upload_limit(
    tmp_path: Path, storage_root: Path, sample_cache: Path
) -> None:
    client = make_client(tmp_path, storage_root, sample_cache, client=("10.0.0.9", 443))
    files = {"file": ("orders.csv", small_csv(), "text/csv")}

    def upload(ip: str) -> int:
        return client.post("/api/datasets", files=files,
                           headers={"X-Forwarded-For": f"{ip}, 10.0.0.9"}).status_code

    first = [upload("203.0.113.1") for _ in range(6)]
    other = upload("203.0.113.2")

    assert first[-1] == 429 and other == 200


# --- 2. one catch-all error handler ------------------------------------------------------

def failing_app(tmp_path: Path) -> TestClient:
    app = create_app(frontend_dist=tmp_path / "no-frontend")

    def boom() -> None:
        raise RuntimeError("database password is hunter2, order 405-1234567-1234567")

    app.add_api_route("/api/boom", boom, methods=["GET"])
    return TestClient(app, raise_server_exceptions=False)


def test_unexpected_errors_return_a_generic_message_with_a_request_id(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    response = failing_app(tmp_path).get("/api/boom")

    body = response.json()
    assert response.status_code == 500
    assert body["error"]["code"] == "internal_error"
    request_id = response.headers["X-Request-ID"]
    assert body["error"]["message"] == (f"Something went wrong on our side. "
                                        f"Reference: {request_id}.")
    assert "hunter2" not in response.text
    assert "hunter2" in caplog.text and request_id in caplog.text  # the detail stays in logs
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_typed_errors_keep_their_messages(client: TestClient) -> None:
    response = client.get("/api/datasets/0123456789ab")

    assert response.status_code == 404
    assert "It may have expired" in response.json()["error"]["message"]


# --- 3. structured request logs ----------------------------------------------------------

def request_lines(caplog: pytest.LogCaptureFixture) -> list[dict]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "saabit.requests"]


def test_run_log_line_has_the_fields_and_no_order_id_or_question(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    dataset = sample_id(client)
    question = "orders for order 171-9198151-1101146 in rajasthan"

    response = client.post(f"/api/datasets/{dataset}/run",
                           params={"question": question},
                           json={"status": "ok", "metric": "orders", "group_by": ["state"]})

    assert response.status_code == 200
    (line,) = [entry for entry in request_lines(caplog) if entry["path"].endswith("/run")]
    assert line["dataset_id"] == dataset
    assert line["plan_status"] == "ok" and line["verified"] is True
    assert line["source"] == "template" and line["llm_provider"] is None
    assert line["outcome"] == "ok" and isinstance(line["latency_ms"], int)
    assert line["request_id"] == response.headers["X-Request-ID"]
    # everything the server logged (httpx's own lines are the test client's side)
    server = "\n".join(r.getMessage() for r in caplog.records
                       if not r.name.startswith("httpx"))
    assert not ORDER_ID.search(server)
    assert "rajasthan" not in server


def test_the_server_runs_without_the_url_access_log() -> None:
    dockerfile = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text("utf-8")

    assert "--no-access-log" in dockerfile.splitlines()[-1]


def test_request_logs_refuse_fields_that_could_carry_data() -> None:
    from app.api.observe import note

    fake = type("R", (), {"state": type("S", (), {"log": {}})()})()
    with pytest.raises(ValueError):
        note(fake, question="revenue in rajasthan")  # type: ignore[arg-type]


# --- 8. security headers ------------------------------------------------------------------

def test_every_response_has_the_security_headers(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "access-control-allow-origin" not in response.headers


# --- 4. upload safety ---------------------------------------------------------------------

def test_excel_formulas_are_never_evaluated(tmp_path: Path) -> None:
    path = tmp_path / "formula.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Order ID", "Date", "Amount"])
    sheet.append(["A-1", "2022-04-01", "=SUM(100,200)"])
    workbook.save(path)

    table = ingest.read_xlsx(path)
    amount = table.head["Amount"].iloc[0]

    # openpyxl never calculates: with no cached value from Excel the cell is blank, not 300
    assert pd.isna(amount)


def test_a_workbook_with_a_macro_inside_is_read_as_data_only(tmp_path: Path) -> None:
    path = tmp_path / "macro.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Order ID", "Date", "Amount"])
    workbook.active.append(["A-1", "2022-04-01", "100"])
    workbook.save(path)
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("xl/vbaProject.bin", b"Attribute VB_Name = \"Evil\"\nShell \"calc\"")

    table = ingest.read_xlsx(path)

    assert list(table.head["Order ID"]) == ["A-1"]


def test_a_path_like_filename_never_becomes_a_path(client: TestClient,
                                                   storage_root: Path) -> None:
    files = {"file": ("..\\..\\..\\Windows\\evil.csv", small_csv(), "text/csv")}

    dataset = client.post("/api/datasets", files=files).json()["dataset_id"]

    assert sorted(p.name for p in (storage_root / dataset).iterdir()) == ["metadata.json",
                                                                          "raw.csv"]
    assert not (storage_root.parent / "Windows").exists()


# --- 5. retention -------------------------------------------------------------------------

def make_dataset(root: Path, dataset_id: str, age_hours: float, now: datetime) -> Path:
    folder = root / dataset_id
    (folder / "cards").mkdir(parents=True)
    created = (now - timedelta(hours=age_hours)).isoformat()
    (folder / "metadata.json").write_text(json.dumps({"created_at": created}), "utf-8")
    return folder


def aged_file(path: Path, age_hours: float, now: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", "utf-8")
    os.utime(path, (now - age_hours * 3600, now - age_hours * 3600))
    return path


def test_retention_deletes_old_datasets_and_cards_but_keeps_the_sample(tmp_path: Path) -> None:
    now = time.time()
    when = datetime.fromtimestamp(now, UTC)
    root, plans, cache = tmp_path / "storage", tmp_path / "plans", tmp_path / "sample_cache"
    old = make_dataset(root, "aaaaaaaaaaaa", 30, when)
    new = make_dataset(root, "bbbbbbbbbbbb", 2, when)
    sample = make_dataset(root, "cccccccccccc", 300, when)
    old_card = aged_file(sample / "cards" / "old.json", 25, now)
    new_card = aged_file(sample / "cards" / "new.json", 1, now)
    cache_card = aged_file(cache / "cards" / "insight.json", 500, now)
    old_plan = aged_file(plans / "old.json", 24 * 8, now)
    new_plan = aged_file(plans / "new.json", 24 * 6, now)

    result = retention.sweep(root, "cccccccccccc", plans, now=now)

    assert not old.exists() and new.exists() and sample.exists()
    assert not old_card.exists() and new_card.exists()
    assert cache_card.exists()  # the prepared sample cache is never touched
    assert not old_plan.exists() and new_plan.exists()
    assert (result.datasets, result.cards, result.plans) == (1, 1, 1)


def test_retention_hours_can_be_overridden(tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAABIT_RETENTION_HOURS", "1")
    now = time.time()
    folder = make_dataset(tmp_path, "aaaaaaaaaaaa", 2, datetime.fromtimestamp(now, UTC))

    retention.sweep(tmp_path, None, tmp_path / "plans", now=now)

    assert not folder.exists()


def test_retention_ignores_folders_that_are_not_datasets(tmp_path: Path) -> None:
    now = time.time()
    other = aged_file(tmp_path / "plan_seed" / "seed.json", 24 * 30, now)

    retention.sweep(tmp_path, None, tmp_path / "plans", now=now)

    assert other.exists()


def test_retention_runs_at_startup(tmp_path: Path, storage_root: Path,
                                   sample_cache: Path) -> None:
    old = make_dataset(storage_root, "aaaaaaaaaaaa", 48, datetime.now(UTC))

    with make_client(tmp_path, storage_root, sample_cache):
        deadline = time.time() + 5
        while old.exists() and time.time() < deadline:
            time.sleep(0.05)

    assert not old.exists()


# --- 7. fallback timeout ------------------------------------------------------------------

def test_nim_gets_30_seconds_and_groq_15(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[float] = []
    real_client = httpx.Client

    def spy(*args: object, timeout: float, transport: object = None) -> httpx.Client:
        seen.append(timeout)
        reply = httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})
        return real_client(transport=httpx.MockTransport(lambda _: reply))

    monkeypatch.setattr(llm.httpx, "Client", spy)
    for name in ("groq", "nim"):
        llm.call_json("s", "u", config=config.ProviderConfig("key", "m", "https://x.test", name))

    assert seen == [15.0, 30.0]


# --- 6. health ----------------------------------------------------------------------------

def test_health_reports_llm_state_and_free_space(client: TestClient,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("NIM_API_KEY", "k")
    monkeypatch.setattr(config, "_last", None)
    states = [client.get("/api/health").json()["llm"]["state"]]
    for provider, status in (("groq", "ok"), ("nim", "ok"), (None, "unavailable")):
        config.record(status, None, provider)
        states.append(client.get("/api/health").json()["llm"]["state"])

    body = client.get("/api/health").json()
    assert states == ["unknown", "ok", "fallback", "down"]
    assert body["storage"]["free_mb"] > 0
    assert {"provider", "model", "status", "reason", "providers"} <= set(body["llm"])


def test_health_says_down_when_no_provider_is_configured(client: TestClient) -> None:
    assert client.get("/api/health").json()["llm"]["state"] == "down"
