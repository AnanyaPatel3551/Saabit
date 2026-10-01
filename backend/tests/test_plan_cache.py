"""Persistent plan cache and prompt layout: re-ask the model only when something changed."""

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from app.core import planner
from app.llm import prompts
from tests.test_planner import FakeLLM, sample_id


@pytest.fixture(autouse=True)
def empty_memory_cache() -> None:
    planner.plan_cache.clear()


def ask(cache: Path, tmp_path: Path, question: str, fake: FakeLLM, **kwargs: object):
    return planner.make_plan(question, sample_id(cache), tmp_path, cache, complete=fake,
                             **kwargs)


def test_persistent_cache_hit_skips_the_llm(sample_cache: Path, tmp_path: Path) -> None:
    fake = FakeLLM({"status": "ok", "metric": "orders"})
    first = ask(sample_cache, tmp_path, "How many orders?", fake)
    planner.plan_cache.clear()  # as after a restart: only the disk copy is left

    second = ask(sample_cache, tmp_path, "how many orders", fake)

    assert len(fake.calls) == 1
    assert (first.cached, second.cached) == (False, True)
    assert second.plan == first.plan
    assert list((tmp_path / "plan_cache").glob("*.json"))


def test_cache_misses_when_the_question_changes(sample_cache: Path, tmp_path: Path) -> None:
    fake = FakeLLM({"status": "ok", "metric": "orders"}, {"status": "ok", "metric": "revenue"})

    ask(sample_cache, tmp_path, "How many orders?", fake)
    other = ask(sample_cache, tmp_path, "What is revenue?", fake)

    assert len(fake.calls) == 2
    assert other.plan.metric == "revenue"


def test_cache_misses_when_the_prompt_version_changes(
    sample_cache: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeLLM({"status": "ok", "metric": "orders"}, {"status": "ok", "metric": "orders"})
    ask(sample_cache, tmp_path, "How many orders?", fake)
    planner.plan_cache.clear()

    monkeypatch.setattr(prompts, "RULES", prompts.RULES + "\n10. A new rule.")
    again = ask(sample_cache, tmp_path, "How many orders?", fake)

    assert len(fake.calls) == 2
    assert again.cached is False


def test_no_cache_forces_a_fresh_call(sample_cache: Path, tmp_path: Path) -> None:
    fake = FakeLLM({"status": "ok", "metric": "orders"}, {"status": "ok", "metric": "orders"})

    ask(sample_cache, tmp_path, "How many orders?", fake)
    fresh = ask(sample_cache, tmp_path, "How many orders?", fake, use_cache=False)

    assert len(fake.calls) == 2
    assert fresh.cached is False


def test_a_corrupt_cache_file_is_a_miss(sample_cache: Path, tmp_path: Path) -> None:
    fake = FakeLLM({"status": "ok", "metric": "orders"}, {"status": "ok", "metric": "orders"})
    ask(sample_cache, tmp_path, "How many orders?", fake)
    planner.plan_cache.clear()
    for path in (tmp_path / "plan_cache").glob("*.json"):
        path.write_text("{not json", encoding="utf-8")

    result = ask(sample_cache, tmp_path, "How many orders?", fake)

    assert result.plan.metric == "orders"
    assert len(fake.calls) == 2


def test_cache_file_holds_the_plan_not_the_prompt(sample_cache: Path, tmp_path: Path) -> None:
    ask(sample_cache, tmp_path, "How many orders?", FakeLLM({"status": "ok", "metric": "orders"}))

    (path,) = (tmp_path / "plan_cache").glob("*.json")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert set(saved) == {"plan", "caveats", "prompt_version", "schema_hash"}
    assert saved["plan"]["metric"] == "orders"


def context(values: dict[str, list[str]]) -> prompts.PromptContext:
    return prompts.PromptContext(date_min=date(2022, 4, 1), date_max=date(2022, 6, 29),
                                 roles=frozenset({"order_id", "order_date", "amount", "state"}),
                                 values=values, counts={})


def test_static_prompt_prefix_is_identical_across_datasets() -> None:
    one = prompts.planner_system_prompt(context({"state": ["Goa", "Kerala"]}))
    two = prompts.planner_system_prompt(replace(context({"state": ["Assam"]}),
                                                date_max=date(2023, 1, 31)))
    static = prompts.static_prompt()

    assert one.startswith(static) and two.startswith(static)
    assert prompts.schema_hash(context({"state": ["Goa"]})) != prompts.schema_hash(
        context({"state": ["Assam"]}))


def test_the_question_is_only_in_the_user_message() -> None:
    system, user = prompts.planner_messages(context({}), "rajsthan ka cancellation kitna hai")

    assert "rajsthan ka cancellation kitna hai" not in system.split("EXAMPLES")[0]
    assert user == "Question: rajsthan ka cancellation kitna hai"
