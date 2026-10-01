"""Run the golden questions through Saabit and print a scorecard (PRD "Evaluation plan").

For every question in eval/questions.yaml and every anchor in eval/golden.yaml:

1. LLM path: the planner reads the question, then both engines run its plan.
2. Expected path: both engines run the plan the question should be read as (no LLM).

A failure is a plan failure when the expected path is right but the LLM path is not, and a
compute failure when the expected path itself is wrong, unverified or errors. "Verified but
wrong" counts expected-path answers marked Verified that differ from the answer key: those are
calculation errors, and any of them makes this script exit with code 1. The answer writer is not
called, so latency here is planning plus computing.

Exit codes: 0 done, 1 verified-but-wrong > 0, 2 stopped early (LLM down) or not set up.

Usage (from the repo root, with GROQ_API_KEY in the environment):
    python eval/eval.py [--provider groq|nim] [--no-cache] [--limit N] [--only s01,x02]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(EVAL_DIR))

import scoring  # noqa: E402

from app.api.errors import SampleUnavailable  # noqa: E402
from app.api.sample import get_sample_cache_dir, shared_sample  # noqa: E402
from app.core import pipeline, planner  # noqa: E402
from app.core.plan import Plan, PlanError  # noqa: E402
from app.llm.client import LLMUnavailable, call_json  # noqa: E402
from app.llm.config import PROVIDERS_ENV, available_providers  # noqa: E402

RESULTS_DIR = EVAL_DIR / "results"
# Seconds between LLM calls, by the first provider in the run. A planner call is about 2,000
# tokens: 16 s keeps Groq's free tier under 8,000 tokens per minute (15 s tipped over late in a
# full run); NIM's trial allows about 40 requests a minute.
SECONDS_PER_CALL = {"groq": 16.0, "nim": 2.0}
RATE_LIMIT_WAIT = 60.0  # after a 429 the client could not ride out, let the minute window clear
RATE_LIMIT_RETRIES = 3
PER_QUESTION_FAILURES = {"timeout", "server_error", "unreachable"}


class Stopped(Exception):
    """The LLM is down for a reason waiting will not fix; the run stops and is saved as partial."""


@dataclass
class Pacer:
    """Spaces LLM calls at least `interval` seconds apart; counts waiting time and tokens."""

    interval: float
    last_call: float | None = None
    slept: float = 0.0
    calls: int = 0
    prompt_tokens: int = 0
    cached_tokens: int = 0
    served_by: dict[str, int] = field(default_factory=dict)  # "provider model" -> calls
    last_served: str | None = None

    def complete(self, system: str, user: str) -> dict[str, Any]:
        if self.last_call is not None:
            wait = self.interval - (time.monotonic() - self.last_call)
            if wait > 0:
                time.sleep(wait)
                self.slept += wait
        self.last_call = time.monotonic()
        self.calls += 1
        result = call_json(system, user)
        self.prompt_tokens += result.usage.get("prompt_tokens", 0)
        self.cached_tokens += result.usage.get("cached_tokens", 0)
        self.last_served = f"{result.provider} {result.model}"
        self.served_by[self.last_served] = self.served_by.get(self.last_served, 0) + 1
        return result.data

    def wait(self, seconds: float) -> None:
        time.sleep(seconds)
        self.slept += seconds


@dataclass
class Run:
    """What one path (LLM or expected plan) produced for one question."""

    status: str | None = None
    reason: str | None = None
    plan: dict | None = None
    result: list[dict] | None = None
    caveats: list[str] = field(default_factory=list)
    verified: bool | None = None
    error: str | None = None
    cached_plan: bool = False
    served_by: str | None = None  # "provider model" of the planner call, None when cached


def load_questions() -> list[dict[str, Any]]:
    """The 50 questions plus the golden anchors, in one shape."""
    questions = yaml.safe_load((EVAL_DIR / "questions.yaml").read_text(encoding="utf-8"))
    entries = [dict(q, source="questions") for q in questions["questions"]]
    golden = yaml.safe_load((EVAL_DIR / "golden.yaml").read_text(encoding="utf-8"))
    for a in golden["anchors"]:
        if a.get("expected_status") == "unsupported":
            entries.append({"id": a["id"], "question": a["question"], "group": "unanswerable",
                            "expected_status": "unsupported", "reason_any": [a["reason_contains"]],
                            "source": "anchors"})
        else:
            entries.append({"id": a["id"], "question": a["question"], "group": "anchor",
                            "expected_status": "ok", "expected": a["expected"],
                            "tolerance": a["tolerance"], "ordered": bool(a["plan"].get("limit")),
                            "expected_plan": a["plan"], "source": "anchors"})
    return entries


def compute(plan: Plan, ctx: dict[str, Any]) -> Run:
    """Both engines on one plan; plan errors come back as text, not exceptions."""
    try:
        card = pipeline.run_plan(ctx["dataset_id"], plan, ctx["root"], ctx["cache"],
                                 cards_dir=ctx["cards"])
    except PlanError as exc:
        return Run(status="ok", plan=plan.model_dump(mode="json"), error=exc.message)
    return Run(status="ok", plan=card.plan, result=card.result, caveats=card.caveats,
               verified=card.verified)


def llm_path(question: str, ctx: dict[str, Any], pacer: Pacer) -> tuple[Run, float]:
    """Planner then engines; returns the run and its latency without pacing waits."""
    slept_before = pacer.slept
    pacer.last_served = None
    start = time.monotonic()
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            planned = planner.make_plan(question, ctx["dataset_id"], ctx["root"], ctx["cache"],
                                        complete=pacer.complete, use_cache=ctx["use_cache"])
            break
        except LLMUnavailable as exc:
            if exc.kind in PER_QUESTION_FAILURES:
                # a slow or failing reply is this question's failure, not a reason to stop
                latency = time.monotonic() - start - (pacer.slept - slept_before)
                return Run(error=f"LLM {exc.kind}: {exc.reason}",
                           served_by=pacer.last_served), latency
            if exc.kind != "rate_limited" or attempt == RATE_LIMIT_RETRIES:
                raise Stopped(f"{exc.kind}: {exc.reason}") from exc
            print(f"    rate limited; waiting {RATE_LIMIT_WAIT:.0f} s and retrying", flush=True)
            pacer.wait(RATE_LIMIT_WAIT)
    plan = planned.plan
    if plan.status != "ok":
        reason = plan.unsupported_reason or (plan.clarification.question if plan.clarification
                                             else None)
        run = Run(status=plan.status, reason=reason, plan=plan.model_dump(mode="json"))
    else:
        run = compute(plan, ctx)
    run.cached_plan, run.served_by = planned.cached, pacer.last_served
    latency = time.monotonic() - start - (pacer.slept - slept_before)
    return run, latency


def value_correct(q: dict[str, Any], run: Run) -> bool:
    """The numbers only (no caveat check), used for verified-but-wrong."""
    return scoring.score_answer(dict(q, caveat_contains=None), run.status, run.reason,
                                run.result, run.caveats)


def score(q: dict[str, Any], got: Run, expected: Run | None, latency: float) -> dict[str, Any]:
    """One scored row: correct, failure type and the verified flags."""
    correct = got.error is None and scoring.score_answer(q, got.status, got.reason, got.result,
                                                         got.caveats)
    row: dict[str, Any] = {
        "id": q["id"], "source": q["source"], "group": q["group"], "question": q["question"],
        "correct": correct,
        # cached plans skip the model, so they are left out of the latency percentiles
        "latency_s": round(latency, 3) if latency and not got.cached_plan else None,
        "cached_plan": got.cached_plan, "served_by": got.served_by,
        "got": {"status": got.status, "reason": got.reason, "plan": got.plan,
                "result": got.result, "caveats": got.caveats, "verified": got.verified,
                "error": got.error},
        "expected": {k: q[k] for k in ("expected_status", "expected", "reason_any",
                                       "caveat_contains") if k in q},
        "failure": None, "verified_but_wrong": False, "verified_but_misread": False,
    }
    if expected is not None:
        expected_ok = expected.error is None and scoring.score_answer(
            q, expected.status, None, expected.result, expected.caveats)
        row["expected_plan_run"] = {"correct": expected_ok, "verified": expected.verified,
                                    "result": expected.result, "caveats": expected.caveats,
                                    "error": expected.error}
        row["verified_but_wrong"] = bool(expected.verified) and not value_correct(q, expected)
        if not correct:
            row["failure"] = "compute" if not expected_ok else "plan"
            row["verified_but_misread"] = bool(got.verified) and expected_ok
    elif not correct:
        row["failure"] = "plan"
    return row


def short(value: Any, limit: int = 160) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def card_lines(title: str, card: dict[str, Any]) -> list[str]:
    s = card
    total = s["answerable"] + s["unanswerable"]
    lines = [f"{title} ({total} questions)",
             f"  answerable correct     {s['answerable_correct']}/{s['answerable']} "
             f"({scoring.pct(s['answerable_correct'], s['answerable'])})",
             f"  refused correctly      {s['refused_correctly']}/{s['unanswerable']} "
             f"({scoring.pct(s['refused_correctly'], s['unanswerable'])})",
             f"  verified but wrong     {s['verified_but_wrong']}   "
             "(calculation errors; must be 0)",
             f"  verified but misread   {s['verified_but_misread']}   "
             "(planner read it differently)",
             f"  plan failures          {s['plan_failures']}",
             f"  compute failures       {s['compute_failures']}"]
    if s["p50_s"] is not None:
        lines.append(f"  latency p50 / p95      {s['p50_s']:.2f} s / {s['p95_s']:.2f} s "
                     "(plan + compute; writer not included)")
    return lines


def markdown(cards: dict[str, dict[str, Any]], meta: dict[str, Any]) -> str:
    """A table ready to paste into the README."""
    served = ", ".join(f"`{k}` × {v}" for k, v in meta["served_by"].items()) or "saved plans only"
    out = [f"Eval run {meta['finished_at']} · planner calls served by {served} · "
           f"{meta['questions']} questions, {meta['llm_calls']} planner calls, "
           f"{meta['plans_from_cache']} saved plans", "",
           "| Measure | Golden questions | Anchors |", "| --- | --- | --- |"]
    q, a = cards["questions"], cards["anchors"]

    def frac(card: dict[str, Any], part: str, whole: str) -> str:
        return f"{card[part]}/{card[whole]} ({scoring.pct(card[part], card[whole])})" \
            if card[whole] else "—"

    def secs(v: float | None) -> str:
        return f"{v:.2f} s" if v is not None else "—"

    out += [f"| Answerable correct | {frac(q, 'answerable_correct', 'answerable')} | "
            f"{frac(a, 'answerable_correct', 'answerable')} |",
            f"| Unanswerable refused | {frac(q, 'refused_correctly', 'unanswerable')} | "
            f"{frac(a, 'refused_correctly', 'unanswerable')} |",
            f"| Verified but wrong | {q['verified_but_wrong']} | {a['verified_but_wrong']} |",
            f"| Plan failures | {q['plan_failures']} | {a['plan_failures']} |",
            f"| Compute failures | {q['compute_failures']} | {a['compute_failures']} |",
            f"| Latency p50 / p95 (plan + compute) | {secs(q['p50_s'])} / {secs(q['p95_s'])} | "
            f"{secs(a['p50_s'])} / {secs(a['p95_s'])} |"]
    return "\n".join(out) + "\n"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, help="run only the first N questions")
    parser.add_argument("--provider", choices=["groq", "nim"],
                        help="use only this provider (default: LLM_PROVIDERS, groq then nim)")
    parser.add_argument("--no-cache", action="store_true",
                        help="ask the model for every question, ignoring saved plans")
    parser.add_argument("--only", nargs="+",
                        help="question ids, comma or space separated, e.g. s01,x02 b05")
    return parser.parse_args(argv)


def select(entries: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.only:
        wanted = {i for part in args.only for i in part.replace(",", " ").split()}
        unknown = wanted - {e["id"] for e in entries}
        if unknown:
            sys.exit(f"Unknown question ids: {', '.join(sorted(unknown))}")
        entries = [e for e in entries if e["id"] in wanted]
    return entries[: args.limit] if args.limit else entries


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.provider:
        os.environ[PROVIDERS_ENV] = args.provider
    providers = available_providers()
    if not providers:
        print("No LLM provider is configured (GROQ_API_KEY / NIM_API_KEY). Run through "
              ".\\tasks.ps1 eval, which loads .env.")
        return 2
    try:
        sample = shared_sample(get_sample_cache_dir())
    except SampleUnavailable as exc:
        print(f"{exc.message} Run: cd backend; python -m app.prepare_sample")
        return 2
    entries = select(load_questions(), args)
    pacer = Pacer(interval=SECONDS_PER_CALL.get(providers[0].name, 16.0))
    rows: list[dict[str, Any]] = []
    stopped: str | None = None
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="saabit-eval-") as tmp:
        ctx = {"dataset_id": sample.dataset_id, "root": Path(tmp) / "storage",
               "cache": get_sample_cache_dir(), "cards": Path(tmp) / "cards",
               "use_cache": not args.no_cache}
        order = " then ".join(f"{p.name} ({p.model})" for p in providers)
        print(f"Saabit eval: {len(entries)} questions via {order}; {pacer.interval:.0f} s "
              f"between planner calls; saved plans {'ignored' if args.no_cache else 'reused'}.",
              flush=True)
        for n, q in enumerate(entries, 1):
            try:
                got, latency = llm_path(q["question"], ctx, pacer)
            except Stopped as exc:
                stopped = f"stopped at {q['id']} ({n}/{len(entries)}): LLM unavailable, {exc}"
                print(f"\n{stopped}\nThe questions after this point were not run.", flush=True)
                break
            expected = compute(Plan.model_validate(q["expected_plan"]), ctx) \
                if "expected_plan" in q else None
            row = score(q, got, expected, latency)
            rows.append(row)
            mark = "OK  " if row["correct"] else f"FAIL ({row['failure']})"
            elapsed = time.monotonic() - started
            source = "saved plan" if got.cached_plan else (got.served_by or "")
            print(f"[{n:>2}/{len(entries)}] {q['id']:<34} {mark:<16} {latency:5.2f}s"
                  f"   {source:<44} elapsed {elapsed / 60:4.1f} min", flush=True)

    cards = {src: scoring.scorecard([r for r in rows if r["source"] == src])
             for src in ("questions", "anchors")}
    meta = {"finished_at": time.strftime("%Y-%m-%d %H:%M"),
            "providers": [f"{p.name} {p.model}" for p in providers],
            "served_by": pacer.served_by, "plans_from_cache": sum(r["cached_plan"] for r in rows),
            "prompt_tokens": pacer.prompt_tokens, "cached_tokens": pacer.cached_tokens,
            "questions": len(rows), "llm_calls": pacer.calls,
            "minutes": round((time.monotonic() - started) / 60, 1), "stopped": stopped}

    served = ", ".join(f"{k}: {v}" for k, v in pacer.served_by.items()) or "none"
    print(f"\nPlanner calls: {pacer.calls} ({served}); "
          f"plans from cache: {meta['plans_from_cache']}; prompt tokens {pacer.prompt_tokens}, "
          f"of which cached {pacer.cached_tokens}.")
    if meta["plans_from_cache"]:
        print(f"NOTE: {meta['plans_from_cache']} questions were answered from saved plans "
              "(plan cache or seed), not the model. Publish only runs made with --no-cache.")
    print()
    for line in card_lines("Golden questions", cards["questions"]) + [""] + \
            card_lines("Golden anchors", cards["anchors"]):
        print(line)
    failed = [r for r in rows if not r["correct"]]
    if failed:
        print("\nFailed questions")
    for r in failed:
        print(f"- {r['id']} [{r['failure']}] {r['question']}")
        print(f"    expected: {short(r['expected'])}")
        got = r["got"]
        print(f"    got:      status={got['status']} error={got['error']} "
              f"reason={short(got['reason'], 100)}")
        print(f"              plan={short(got['plan'])}")
        print(f"              result={short(got['result'])}")
        if "expected_plan_run" in r:
            print(f"    expected plan run: correct={r['expected_plan_run']['correct']} "
                  f"verified={r['expected_plan_run']['verified']}")

    # Only a full run replaces latest.*; --only and --limit runs never overwrite it.
    name = "partial" if (args.only or args.limit or stopped) else "latest"
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / f"{name}.json").write_text(
        json.dumps({"meta": meta, "scorecards": cards, "rows": rows}, indent=2,
                   ensure_ascii=False, default=str), encoding="utf-8")
    (RESULTS_DIR / f"{name}.md").write_text(markdown(cards, meta), encoding="utf-8")
    print(f"\nSaved eval/results/{name}.json and {name}.md ({meta['minutes']} min).")
    wrong = cards["questions"]["verified_but_wrong"] + cards["anchors"]["verified_but_wrong"]
    if wrong:
        return 1
    return 2 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
