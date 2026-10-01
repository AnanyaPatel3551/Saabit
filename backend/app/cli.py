"""Command line: check the LLM, plan, ask, or show the prompt for a question.

    python -m app.cli llm-check                                     (needs GROQ_API_KEY)
    python -m app.cli prompt "rajsthan ka cancellation kitna hai"   (works offline)
    python -m app.cli plan "top 5 states by revenue"                (needs GROQ_API_KEY)
    python -m app.cli ask "revenue by month"                        (plan, then run it)

Uses the prepared sample unless --dataset names another cleaned dataset.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from app.api.sample import get_sample_cache_dir, read_cached_sample
from app.core import pipeline, storage
from app.core.plan import PlanError
from app.core.planner import LLMUnavailable, make_plan, prompt_for
from app.llm import client
from app.llm.config import LLMConfig


def default_dataset(cache: Path) -> str:
    sample = read_cached_sample(cache)
    if sample is None:
        sys.exit("The sample is not prepared. Run: python -m app.prepare_sample")
    return sample.dataset_id


def show(label: str, value: object) -> None:
    print(f"--- {label}")
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def llm_check() -> int:
    """Is the model listed for this key, and does a tiny JSON call work? Never prints the key."""
    config = LLMConfig.from_env()
    print(f"provider: groq   model: {config.model}   base url: {config.base_url}")
    print(f"GROQ_API_KEY set: {'yes' if config.api_key else 'no'}")
    try:
        started = time.perf_counter()
        models = client.list_models(config)
        print(f"models listed: {len(models)} ({time.perf_counter() - started:.2f}s)")
        if config.model not in models:
            gpt = [m for m in models if "gpt-oss" in m or "llama" in m]
            print(f"FAIL: '{config.model}' is not in this key's model list. Similar: {gpt}")
            return 1
        print(f"'{config.model}' is listed")
        result = client.call_json("You reply with JSON only.",
                                  'Return this JSON object exactly: {"ok": true}', config=config)
    except LLMUnavailable as error:
        print(f"FAIL: {error.kind}: {error.reason}")
        return 1
    except client.ModelOutputError as error:
        print(f"FAIL: the model replied, but not with JSON: {error}")
        return 1
    ok = result.data == {"ok": True}
    print(f"JSON call: {'ok' if ok else 'unexpected reply ' + str(result.data)}, "
          f"latency {result.latency_ms} ms, tokens {result.usage}")
    for header, value in result.rate_limits.items():
        print(f"  {header}: {value}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["llm-check", "plan", "ask", "prompt"])
    parser.add_argument("question", nargs="?", default="")
    parser.add_argument("--dataset", help="dataset id (default: the prepared sample)")
    parser.add_argument("--fake-answer", metavar="TEXT",
                        help="ask only: use TEXT as the writer's sentence to test the checker")
    args = parser.parse_args(argv)
    if args.command == "llm-check":
        return llm_check()
    if not args.question:
        parser.error(f"{args.command} needs a question")
    root, cache = storage.storage_root(), get_sample_cache_dir()
    dataset_id = args.dataset or default_dataset(cache)

    if args.command == "prompt":
        system, user = prompt_for(args.question, dataset_id, root, cache)
        print("=== SYSTEM ===")
        print(system)
        print("=== USER ===")
        print(user)
        return 0
    calls: list[client.CallResult] = []

    def ask_model(system: str, user: str) -> dict[str, Any]:
        result = client.call_json(system, user)
        calls.append(result)
        return result.data

    try:
        result = make_plan(args.question, dataset_id, root, cache, complete=ask_model)
    except LLMUnavailable as error:
        print(f"{error.message}\n({error.kind}: {error.reason})", file=sys.stderr)
        return 2
    show("plan" + (" (cached)" if result.cached else ""), result.plan.model_dump(exclude_none=True))
    for number, call in enumerate(calls, 1):
        print(f"--- LLM call {number}: {call.latency_ms} ms, tokens {call.usage}")
    if result.caveats:
        show("caveats", result.caveats)
    if args.command == "ask" and result.plan.status == "ok":
        try:
            card = pipeline.run_plan(dataset_id, result.plan, root, cache)
        except PlanError as error:
            print(error.message, file=sys.stderr)
            return 1
        show("result" + ("" if card.verified else " (NOT verified)"), card.result or {
            "sql": card.sql_result, "pandas": card.pandas_result})
        show("caveats", card.caveats)
        print(f"--- evidence card: {card.card_id} ({card.row_count} source rows)")
        print_answer(args.question, card, ask_model, args.fake_answer, calls)
    return 0


def print_answer(
    question: str, card: Any, ask_model: Any, fake: str | None, calls: list[client.CallResult]
) -> None:
    """Write and show the answer sentence; with --fake-answer, show what the checker did."""
    from app.core import narrate
    from app.core.plan import Plan

    def fake_writer(system: str, user: str) -> dict[str, Any]:
        return {"sentence": fake}

    calls_before = len(calls)
    answer = narrate.write_answer(question, Plan.model_validate(card.plan), card.result,
                                  card.verified, card.sql_result, card.pandas_result,
                                  complete=fake_writer if fake is not None else ask_model)
    if answer.rejected is not None:
        print(f"--- rejected sentence: {answer.rejected}")
        print(f"    unmatched: {answer.unmatched}")
    print(f"--- answer ({answer.source})")
    print(answer.text if answer.text is not None else answer.note)
    for number, call in enumerate(calls[calls_before:], calls_before + 1):
        print(f"--- LLM call {number} (writer): {call.latency_ms} ms, tokens {call.usage}")


if __name__ == "__main__":
    sys.exit(main())
