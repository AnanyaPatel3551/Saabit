"""The pre-warmed plan seed: found without an LLM call, stale entries ignored, never deleted."""

import json
import shutil
import time
from pathlib import Path

import pytest

from app import plan_seed
from app.core import planner, retention
from app.llm import prompts
from tests.test_planner import FakeLLM, sample_id


@pytest.fixture(autouse=True)
def empty_memory_cache() -> None:
    planner.plan_cache.clear()


def seeded_cache(sample_cache: Path, tmp_path: Path, question: str, plan: dict,
                 prompt_version: str | None = None) -> tuple[Path, Path]:
    """A copy of the sample cache folder with a one-entry seed loaded into it."""
    cache = tmp_path / "cache"
    shutil.copytree(sample_cache, cache)
    context = planner.build_context(sample_id(cache), tmp_path / "storage", cache)
    key = planner.cache_key(context.prompt, question)
    entry = {"question": question, "prompt_version": prompt_version or key[0],
             "schema_hash": key[1], "normalised": key[2], "plan": plan, "caveats": []}
    seed = tmp_path / "plan_seed.json"
    seed.write_text(json.dumps({"_comment": plan_seed.HEADER, "entries": [entry]}), "utf-8")
    return cache, seed


def test_seed_hit_skips_the_llm(sample_cache: Path, tmp_path: Path) -> None:
    cache, seed = seeded_cache(sample_cache, tmp_path, "How many orders?",
                               {"status": "ok", "metric": "orders"})
    assert plan_seed.load(cache, seed) == (1, 1)
    fake = FakeLLM()

    result = planner.make_plan("how many orders", sample_id(cache), tmp_path / "s", cache,
                               complete=fake)

    assert fake.calls == []
    assert result.cached and result.plan.metric == "orders"


def test_stale_seed_entry_is_ignored(sample_cache: Path, tmp_path: Path) -> None:
    cache, seed = seeded_cache(sample_cache, tmp_path, "How many orders?",
                               {"status": "ok", "metric": "revenue"},
                               prompt_version="an-older-prompt")
    assert plan_seed.load(cache, seed) == (0, 1)
    fake = FakeLLM({"status": "ok", "metric": "orders"})

    result = planner.make_plan("How many orders?", sample_id(cache), tmp_path / "s", cache,
                               complete=fake)

    assert len(fake.calls) == 1 and result.plan.metric == "orders"


def test_a_prompt_edit_makes_the_seed_go_stale(sample_cache: Path, tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    cache, seed = seeded_cache(sample_cache, tmp_path, "How many orders?",
                               {"status": "ok", "metric": "orders"})
    plan_seed.load(cache, seed)
    monkeypatch.setattr(prompts, "RULES", prompts.RULES + "\n10. A new rule.")
    fake = FakeLLM({"status": "ok", "metric": "orders"})

    planner.make_plan("How many orders?", sample_id(cache), tmp_path / "s", cache,
                      complete=fake)

    assert len(fake.calls) == 1


def test_retention_never_deletes_the_seed(sample_cache: Path, tmp_path: Path) -> None:
    cache, seed = seeded_cache(sample_cache, tmp_path, "How many orders?",
                               {"status": "ok", "metric": "orders"})
    plan_seed.load(cache, seed)
    seeded = list((cache / planner.SEED_DIR).glob("*.json"))

    retention.sweep(tmp_path / "storage", None, tmp_path / "plans", now=time.time() + 400 * 86400)

    assert seeded and all(path.exists() for path in seeded)


def test_export_keeps_only_plans_scored_correct(
    sample_cache: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(plan_seed, "known_questions", lambda: ["right one", "wrong one",
                                                               "never asked"])
    fake = FakeLLM({"status": "ok", "metric": "orders"}, {"status": "ok", "metric": "units"})
    for question in ("right one", "wrong one"):
        planner.make_plan(question, sample_id(sample_cache), tmp_path, sample_cache,
                          complete=fake)
    results = tmp_path / "latest.json"
    results.write_text(json.dumps({"meta": {}, "rows": [
        {"question": "right one", "correct": True}, {"question": "wrong one", "correct": False},
    ]}), "utf-8")
    out = tmp_path / "seed.json"

    counts = plan_seed.export(sample_cache, results, out)

    entries = json.loads(out.read_text("utf-8"))["entries"]
    assert [e["question"] for e in entries] == ["right one"]
    assert counts == {"exported": 1, "not cached": 1, "scored wrong": 1}


def test_export_refuses_a_partial_eval_run(sample_cache: Path, tmp_path: Path) -> None:
    results = tmp_path / "latest.json"
    results.write_text(json.dumps({"meta": {"stopped": "rate limited"}, "rows": []}), "utf-8")

    with pytest.raises(SystemExit):
        plan_seed.export(sample_cache, results, tmp_path / "seed.json")
