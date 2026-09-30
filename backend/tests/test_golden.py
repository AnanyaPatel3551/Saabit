"""Golden anchors: every plan in eval/golden.yaml reproduces its frozen value, verified.

eval/golden.yaml was computed by the independent notebook and is never edited. If a test
here fails, the code is wrong, not the anchor.
"""

import json
from pathlib import Path

import pytest
import yaml

from app.core.pipeline import run_plan
from app.core.plan import Plan

GOLDEN = Path(__file__).resolve().parents[2] / "eval" / "golden.yaml"
ANCHORS = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))["anchors"]


def anchor_param(anchor: dict) -> object:
    if "plan" in anchor:
        return pytest.param(anchor, id=anchor["id"])
    return pytest.param(anchor, id=anchor["id"],
                        marks=pytest.mark.skip(reason="no plan: needs the LLM planner (Phase 5)"))


@pytest.mark.parametrize("anchor", [anchor_param(a) for a in ANCHORS])
def test_golden_anchor_is_reproduced_and_verified(
    anchor: dict, real_sample_cache: Path, tmp_path: Path
) -> None:
    sample_id = json.loads((real_sample_cache / "metadata.json").read_text("utf-8"))["dataset_id"]

    card = run_plan(sample_id, Plan.model_validate(anchor["plan"]), tmp_path, real_sample_cache)

    assert card.verified, card.mismatches
    expected, tolerance = anchor["expected"], anchor["tolerance"]
    if isinstance(expected, dict):
        key = anchor["plan"]["group_by"][0]
        got = {row[key]: row["value"] for row in card.result}
        assert set(got) == set(expected)
        for group, value in expected.items():
            assert abs(got[group] - value) <= tolerance, (group, got[group], value)
    else:
        assert len(card.result) == 1
        assert abs(card.result[0]["value"] - expected) <= tolerance, card.result[0]
