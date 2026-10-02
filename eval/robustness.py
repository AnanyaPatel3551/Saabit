"""Robustness checks (PRD "Other tests"): remove a column, get the matching "not available".

No LLM. Each case uploads a 20,000-row slice of the sample through the real API (in-process),
confirms the detected roles, then checks the capability report and that a plan needing the
missing column is refused with a readable message. The sample has no cost column, so the cost
case checks the unchanged file: profit and margin must be reported as unavailable.

Usage (from the repo root):  python eval/robustness.py
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.api.datasets import get_storage_root  # noqa: E402
from app.main import create_app  # noqa: E402

SAMPLE = ROOT / "data" / "sample" / "amazon_sale_report.csv"
SLICE_ROWS = 20_000  # stays well under the 25 MB upload limit


@dataclass(frozen=True)
class Case:
    name: str
    drop: str | None  # raw column removed from the file
    role: str | None  # role that must then be missing
    topic: str  # capability topic that must be in cannot_answer
    reason_word: str  # word the capability reason must contain
    plan: dict[str, Any] | None  # a plan that needs the column; /run must refuse it
    error_word: str | None  # word the /run error message must contain


def plan(metric: str, group_by: list[str] | None = None) -> dict[str, Any]:
    return {"status": "ok", "metric": metric, "group_by": group_by or [], "filters": []}


CASES = [
    Case("cost column (the sample has none)", None, None, "profit and margin", "cost", None, None),
    Case("status column removed", "Status", "status", "cancellation rate", "status",
         plan("cancellation_rate"), "status"),
    Case("state column removed", "ship-state", "state", "breakdown by state", "state",
         plan("orders", ["state"]), "state"),
]


def csv_bytes(rows: pd.DataFrame, drop: str | None) -> bytes:
    data = rows.drop(columns=[drop]) if drop else rows
    buffer = io.StringIO()
    data.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")


def run_case(client: TestClient, rows: pd.DataFrame, case: Case) -> list[tuple[str, bool, str]]:
    """Upload, confirm, then the checks for one case: (check, passed, detail)."""
    checks: list[tuple[str, bool, str]] = []
    upload = client.post("/api/datasets",
                         files={"file": ("slice.csv", csv_bytes(rows, case.drop), "text/csv")})
    if upload.status_code != 200:
        return [("upload", False, upload.text[:200])]
    dataset = upload.json()
    client.headers["X-Dataset-Key"] = dataset["access_key"]  # this upload's private key
    roles = {r["role"]: r["column"] for r in dataset["roles"]}
    if case.role:
        checks.append((f"role '{case.role}' not detected", roles.get(case.role) is None,
                       f"detected: {roles.get(case.role)}"))
    confirm = client.post(f"/api/datasets/{dataset['dataset_id']}/confirm", json={"roles": roles})
    if confirm.status_code != 200:
        return checks + [("confirm", False, confirm.text[:200])]
    cannot = {i["topic"]: i["reason"] for i in confirm.json()["capability"]["cannot_answer"]}
    reason = cannot.get(case.topic, "")
    checks.append((f"'{case.topic}' listed as cannot answer, reason mentions '{case.reason_word}'",
                   case.reason_word in reason.lower(), reason or "topic missing"))
    if case.plan:
        run = client.post(f"/api/datasets/{dataset['dataset_id']}/run", json=case.plan)
        message = run.json().get("error", {}).get("message", "") if run.status_code >= 400 else ""
        checks.append((f"/run {case.plan['metric']} {case.plan['group_by']} refused, message "
                       f"mentions '{case.error_word}'",
                       400 <= run.status_code < 500 and case.error_word in message.lower(),
                       f"HTTP {run.status_code}: {message or run.text[:120]}"))
    return checks


def main() -> int:
    os.environ.pop("GROQ_API_KEY", None)  # no LLM: /run falls back to template sentences
    rows = pd.read_csv(SAMPLE, nrows=SLICE_ROWS, low_memory=False)
    failures = 0
    with tempfile.TemporaryDirectory(prefix="saabit-robust-") as tmp:
        app = create_app()
        app.dependency_overrides[get_storage_root] = lambda: Path(tmp)
        with TestClient(app) as client:
            print(f"Robustness: {len(CASES)} cases on a {SLICE_ROWS:,}-row slice of the sample")
            for case in CASES:
                print(f"\n{case.name}")
                for check, passed, detail in run_case(client, rows, case):
                    failures += not passed
                    print(f"  {'PASS' if passed else 'FAIL'}  {check}\n        {detail}")
    print(f"\n{'All checks passed.' if not failures else f'{failures} check(s) failed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
