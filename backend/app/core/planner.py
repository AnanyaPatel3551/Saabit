"""Question -> validated plan. The LLM only proposes the plan; code checks every part of it.

The model's JSON goes through the same checks as a hand-written plan (Pydantic, validate_plan,
snap_values). A rejected plan is retried once with the reason; a second rejection becomes an
honest "could not understand" plan instead of a guess (FR-4.2, FR-4.3).
"""

import hashlib
import json
import logging
import os
import re
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.core import compile_sql, pipeline, storage
from app.core.metrics import DIMENSIONS
from app.core.plan import DatasetInfo, Plan, PlanError, snap_values, validate_plan
from app.llm.client import LLMUnavailable, ModelOutputError, complete_json
from app.llm.prompts import (
    MAX_VALUES,
    PromptContext,
    planner_messages,
    prompt_version,
    schema_hash,
)

__all__ = ["LLMUnavailable", "PlannerResult", "make_plan", "plan_cache", "prompt_for"]

CACHE_SIZE = 256
PLAN_CACHE_ENV = "SAABIT_PLAN_CACHE"
CLARIFY_MIN_OPTIONS = 2
CLARIFY_MAX_OPTIONS = 4
NOT_UNDERSTOOD = ("Saabit could not understand this question well enough to answer it safely. "
                  "Try naming the measure (revenue, orders, units, average order value or "
                  "cancellation rate) and any state, month or fulfilment type.")

Complete = Callable[[str, str], dict[str, Any]]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlannerResult:
    plan: Plan
    caveats: list[str] = field(default_factory=list)
    cached: bool = False


CacheKey = tuple[str, str, str]  # prompt version, dataset schema hash, normalised question


class PlanCache:
    """Plans in memory by cache key, least recently used dropped first."""

    def __init__(self, size: int = CACHE_SIZE) -> None:
        self.size = size
        self.items: OrderedDict[CacheKey, PlannerResult] = OrderedDict()

    def get(self, key: CacheKey) -> PlannerResult | None:
        if key not in self.items:
            return None
        self.items.move_to_end(key)
        return self.items[key]

    def put(self, key: CacheKey, result: PlannerResult) -> None:
        self.items[key] = result
        self.items.move_to_end(key)
        while len(self.items) > self.size:
            self.items.popitem(last=False)

    def clear(self) -> None:
        self.items.clear()


plan_cache = PlanCache()


def normalise_question(question: str) -> str:
    """Casefold, collapse spaces and trim end punctuation, so trivial variants share a plan."""
    return re.sub(r"\s+", " ", question.casefold()).strip(" ?.!,;:")


@dataclass(frozen=True)
class PlannerContext:
    info: DatasetInfo
    prompt: PromptContext


def build_context(dataset_id: str, storage_root: Path, sample_cache: Path) -> PlannerContext:
    """Everything the planner may use about a dataset: schema-level facts, never rows."""
    context = pipeline.load_context(dataset_id, storage_root, sample_cache)
    metadata = json.loads((context.folder / "metadata.json").read_text(encoding="utf-8"))
    capability = (metadata.get("data_check") or {}).get("capability") or {}
    values: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    # info outlives this block (snapping happens after the model replies), so it gets the
    # database path, not the short-lived connection below.
    info = pipeline.dataset_info(context)
    with compile_sql.connect(context.query_db) as con:
        for dimension in DIMENSIONS.values():
            if not dimension.filterable or dimension.role not in context.roles:
                continue
            count = compile_sql.distinct_count(con, dimension.column)
            if count <= MAX_VALUES:
                values[dimension.name] = compile_sql.distinct_values(con, dimension.column)
            else:
                counts[dimension.name] = count
    prompt = PromptContext(
        date_min=info.date_min,
        date_max=info.date_max,
        roles=context.roles,
        values=values,
        counts=counts,
        cannot_answer=[f"{i['topic']}: {i['reason']}" for i in capability.get("cannot_answer", [])],
        partial_months=context.partial_months,
    )
    return PlannerContext(info=info, prompt=prompt)


def check_plan(raw: dict[str, Any], info: DatasetInfo) -> tuple[Plan, list[str]]:
    """Run the model's plan through the same checks as a hand-written plan."""
    plan = Plan.model_validate(raw)
    if plan.status == "ok":
        plan, caveats = validate_plan(plan, info)
        return snap_values(plan, info), caveats
    if plan.status == "needs_clarification":
        options = plan.clarification.options if plan.clarification else []
        if plan.clarification is None or not plan.clarification.question.strip():
            raise ValueError("needs_clarification requires a clarification question")
        if not CLARIFY_MIN_OPTIONS <= len(options) <= CLARIFY_MAX_OPTIONS:
            raise ValueError("a clarification needs 2 to 4 options")
        return plan, []
    if not (plan.unsupported_reason or "").strip():
        raise ValueError("an unsupported plan needs unsupported_reason")
    return plan, []


def describe(error: Exception) -> str:
    """A short reason the model can act on, without echoing its whole output."""
    if isinstance(error, ValidationError):
        first = error.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "plan"
        return f"{where}: {first['msg']}"
    if isinstance(error, PlanError):
        return error.message
    return str(error)


def plan_cache_dir() -> Path:
    """Where planned questions are kept on disk (SAABIT_PLAN_CACHE, default storage/plan_cache)."""
    return Path(os.environ.get(PLAN_CACHE_ENV) or storage.storage_root() / "plan_cache")


def cache_key(prompt: PromptContext, question: str) -> CacheKey:
    """(prompt version, dataset schema hash, normalised question)."""
    return prompt_version(), schema_hash(prompt), normalise_question(question)


def disk_path(key: CacheKey) -> Path:
    digest = hashlib.sha256("\n".join(key).encode("utf-8")).hexdigest()[:32]
    return plan_cache_dir() / f"{digest}.json"


def read_disk(key: CacheKey) -> PlannerResult | None:
    """A saved plan for this key, or None. A damaged file is treated as a miss."""
    path = disk_path(key)
    if not path.is_file():
        return None
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        return PlannerResult(plan=Plan.model_validate(saved["plan"]),
                             caveats=list(saved["caveats"]))
    except (OSError, ValueError, KeyError, ValidationError):
        logger.info("plan cache file %s is unreadable; asking the model again", path.name)
        return None


def write_disk(key: CacheKey, result: PlannerResult) -> None:
    """Save a validated plan atomically. Only the plan is stored, never the prompt."""
    path = disk_path(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"plan": result.plan.model_dump(mode="json"), "caveats": result.caveats,
                   "prompt_version": key[0], "schema_hash": key[1]}
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)
    except OSError as error:
        logger.info("plan cache write failed (%s); continuing without it", type(error).__name__)


def make_plan(
    question: str,
    dataset_id: str,
    storage_root: Path,
    sample_cache: Path,
    complete: Complete | None = None,
    use_cache: bool = True,
) -> PlannerResult:
    """Plan a question for a dataset: cached, validated, retried once, never a guess.

    The cache (memory, then disk) is keyed by prompt version, dataset schema hash and the
    normalised question, so editing the prompt or confirming a different file re-asks the
    model. use_cache=False always asks the model (and refreshes the cache).
    """
    context = build_context(dataset_id, storage_root, sample_cache)
    key = cache_key(context.prompt, question)
    if use_cache:
        cached = plan_cache.get(key) or read_disk(key)
        if cached is not None:
            plan_cache.put(key, cached)
            return PlannerResult(plan=cached.plan, caveats=cached.caveats, cached=True)
    ask = complete or complete_json
    error: str | None = None
    for attempt in (1, 2):
        system, user = planner_messages(context.prompt, question, error)
        try:
            plan, caveats = check_plan(ask(system, user), context.info)
        except LLMUnavailable:
            raise
        except (ModelOutputError, ValidationError, PlanError, ValueError, TypeError) as exc:
            error = describe(exc)
            logger.info("plan attempt %d rejected: %s", attempt, error)
            continue
        result = PlannerResult(plan=plan, caveats=caveats)
        plan_cache.put(key, result)
        write_disk(key, result)
        return result
    return PlannerResult(plan=Plan(status="unsupported", unsupported_reason=NOT_UNDERSTOOD))


def prompt_for(
    question: str, dataset_id: str, storage_root: Path, sample_cache: Path
) -> tuple[str, str]:
    """The exact (system, user) messages that would be sent for this question."""
    return planner_messages(build_context(dataset_id, storage_root, sample_cache).prompt,
                            question)
