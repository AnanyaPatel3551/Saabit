"""Read-only summary of how Saabit is tested, for the "How we test" page.

It only reads files the eval and test tools write; nothing here runs a test or calls an LLM.
Anything not yet produced comes back as null, and the page shows "pending".

- eval/results/latest.json   python eval/eval.py (full runs only)
- eval/results/baseline.json python eval/baseline/score_baseline.py
- eval/results/tests.json    .\\tasks.ps1 test
"""

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

EVAL_DIR_ENV = "SAABIT_EVAL_DIR"
DEFAULT_EVAL_DIR = Path(__file__).resolve().parents[3] / "eval"

router = APIRouter(prefix="/api", tags=["eval"])


class Score(BaseModel):
    correct: int
    total: int


class EvalRun(BaseModel):
    """One full eval run: the 50 golden questions and the 15 anchors."""

    answerable: Score
    refused: Score
    verified_but_wrong: int
    anchors_answerable: Score
    anchors_refused: Score
    served_by: list[str]
    finished_at: str
    used_saved_plans: bool


class Baseline(BaseModel):
    answerable: Score
    refused: Score
    product: str | None


class Tests(BaseModel):
    passed: int
    skipped: int
    date: str


class EvalSummary(BaseModel):
    eval: EvalRun | None
    baseline: Baseline | None
    tests: Tests | None


def eval_dir() -> Path:
    return Path(os.environ.get(EVAL_DIR_ENV) or DEFAULT_EVAL_DIR)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def eval_run(data: dict[str, Any] | None) -> EvalRun | None:
    """A complete run only; a stopped or flagged run is not shown as a result."""
    if not data or data.get("meta", {}).get("stopped") or data["meta"].get("needs_fresh_run"):
        return None
    try:
        q, a, meta = data["scorecards"]["questions"], data["scorecards"]["anchors"], data["meta"]
        return EvalRun(
            answerable=Score(correct=q["answerable_correct"], total=q["answerable"]),
            refused=Score(correct=q["refused_correctly"], total=q["unanswerable"]),
            verified_but_wrong=q["verified_but_wrong"] + a["verified_but_wrong"],
            anchors_answerable=Score(correct=a["answerable_correct"], total=a["answerable"]),
            anchors_refused=Score(correct=a["refused_correctly"], total=a["unanswerable"]),
            served_by=sorted(meta.get("served_by") or {}),
            finished_at=meta["finished_at"],
            used_saved_plans=bool(meta.get("plans_from_cache")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def baseline(data: dict[str, Any] | None) -> Baseline | None:
    try:
        return Baseline.model_validate(data) if data and data["answerable"]["total"] else None
    except (KeyError, TypeError, ValueError):
        return None


def tests(data: dict[str, Any] | None) -> Tests | None:
    try:
        return Tests.model_validate(data) if data else None
    except ValueError:
        return None


@router.get("/eval-summary", response_model=EvalSummary)
def eval_summary() -> EvalSummary:
    """The latest full eval, the baseline and the test count, each null until produced."""
    folder = eval_dir() / "results"
    return EvalSummary(eval=eval_run(read_json(folder / "latest.json")),
                       baseline=baseline(read_json(folder / "baseline.json")),
                       tests=tests(read_json(folder / "tests.json")))
