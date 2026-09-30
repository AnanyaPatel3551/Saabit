"""Live planner checks against the real Groq API. Skipped unless GROQ_API_KEY is set.

    $env:GROQ_API_KEY = "..."; .\\.venv\\Scripts\\python.exe -m pytest -m live -v
"""

import json
import os
import re
import time
from pathlib import Path

import pytest
import yaml

from app.core import planner
from app.core.plan import Plan, snap_values, validate_plan

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("GROQ_API_KEY"), reason="GROQ_API_KEY is not set"),
]

GOLDEN = Path(__file__).resolve().parents[2] / "eval" / "golden.yaml"
ANCHORS = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))["anchors"]


def essentials(plan: dict) -> dict:
    """The parts of a plan that decide the answer, in a comparable form."""
    filters = sorted(
        (f["column"], "eq" if f.get("op", "eq") in ("eq", "in") and len(f["values"]) == 1
         else f.get("op", "eq"), tuple(sorted(f["values"])))
        for f in plan.get("filters") or []
    )
    parts = {
        "metric": plan.get("metric"),
        "group_by": sorted(plan.get("group_by") or []),
        "filters": filters,
        "date_range": plan.get("date_range"),
    }
    if plan.get("limit") is not None:
        parts["limit"] = plan["limit"]
        parts["sort"] = plan.get("sort")
    return parts


RATE_LIMIT_ATTEMPTS = 6
FALLBACK_WAIT_SECONDS = 20.0


def plan_within_rate_limits(question: str, sample_id: str, root: Path, cache: Path):
    """The free tier allows ~4 planner calls a minute; wait out 429s instead of failing."""
    for attempt in range(1, RATE_LIMIT_ATTEMPTS + 1):
        try:
            return planner.make_plan(question, sample_id, root, cache)
        except planner.LLMUnavailable as error:
            if error.kind != "rate_limited" or attempt == RATE_LIMIT_ATTEMPTS:
                raise
            match = re.search(r"retry after ([\d.]+)s", error.reason)
            time.sleep(float(match.group(1)) + 1 if match else FALLBACK_WAIT_SECONDS)
    raise AssertionError("unreachable")


@pytest.mark.parametrize("anchor", ANCHORS, ids=[a["id"] for a in ANCHORS])
def test_golden_question_is_planned_like_its_anchor(
    anchor: dict, real_sample_cache: Path, tmp_path: Path
) -> None:
    planner.plan_cache.clear()
    sample_id = json.loads((real_sample_cache / "metadata.json").read_text("utf-8"))["dataset_id"]

    result = plan_within_rate_limits(anchor["question"], sample_id, tmp_path, real_sample_cache)

    if "plan" in anchor:
        # The planner's output has been through validate_plan and snap_values (for example a
        # June range is clipped to the last day with data, 2022-06-29). Put the anchor's plan
        # through the same checks, so both sides are compared as the query that would run.
        info = planner.build_context(sample_id, tmp_path, real_sample_cache).info
        checked, _ = validate_plan(Plan.model_validate(anchor["plan"]), info)
        expected = snap_values(checked, info).model_dump(mode="json")
        got = result.plan.model_dump(mode="json")
        assert essentials(got) == essentials(expected), got
    else:
        assert result.plan.status == anchor["expected_status"]
        assert anchor["reason_contains"] in (result.plan.unsupported_reason or "").lower()
