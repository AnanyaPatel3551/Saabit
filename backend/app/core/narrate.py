"""Write the answer sentence with the LLM, with template fallbacks (FR-7.1 to FR-7.3, D7).

The LLM sees the question, a summary of the plan and at most 20 result rows. Its sentence is
used only if every number in it passes the number checker; otherwise, or when the LLM is
unavailable, a template sentence is used. Unverified results get no sentence at all.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.core import numcheck, templates
from app.core.metrics import METRICS
from app.core.plan import Plan

MAX_TABLE_ROWS = 20  # FR-7.1
MAX_SENTENCES = 2
SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
UNVERIFIED_LISTED = 5

Complete = Callable[[str, str], dict[str, Any]]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Answer:
    """The sentence shown to the user and where it came from."""

    text: str | None  # None when the result could not be verified
    source: str  # "llm", "template" or "unverified"
    note: str | None = None  # the "Could not verify" message, with both values
    unmatched: list[str] = field(default_factory=list)  # numbers the checker rejected
    rejected: str | None = None  # the LLM sentence that was replaced, if any


def formatted_rows(plan: Plan, rows: list[dict]) -> list[dict]:
    """Rows with ready-to-copy text for each number, so the LLM does not format by itself."""
    metric = plan.metric or ""
    out = []
    for row in rows[:MAX_TABLE_ROWS]:
        item = dict(row)
        value = row.get("value")
        item["value_text"] = templates.format_value(metric, value)
        if metric in ("revenue", "aov") and value is not None and abs(value) >= 100_000:
            item["value_short"] = templates.format_inr(value, short=True)
        item["orders_text"] = templates.format_count(row["orders"])
        out.append(item)
    return out


def plan_summary(plan: Plan) -> dict:
    metric = METRICS[plan.metric or "orders"]
    return {
        "metric": metric.label,
        "definition": metric.definition,
        "group_by": list(plan.group_by),
        "filters": [f.model_dump() for f in plan.filters],
        "date_range": plan.date_range.model_dump(mode="json") if plan.date_range else None,
    }


def could_not_verify(plan: Plan, sql_rows: list[dict], pandas_rows: list[dict]) -> str:
    """FR-6.2: no sentence, just both engines' values."""
    def summary(rows: list[dict]) -> str:
        parts = []
        for row in rows[:UNVERIFIED_LISTED]:
            value = templates.format_value(plan.metric or "", row.get("value"))
            label = templates.group_label(plan, row) if plan.group_by else ""
            parts.append(f"{label} {value}".strip())
        more = ", ..." if len(rows) > UNVERIFIED_LISTED else ""
        return (", ".join(parts) + more) or "no rows"

    return ("Could not verify this answer: the two calculation engines disagree. "
            f"SQL: {summary(sql_rows)}. pandas: {summary(pandas_rows)}.")


def write_answer(
    question: str,
    plan: Plan,
    rows: list[dict],
    verified: bool,
    sql_rows: list[dict] | None = None,
    pandas_rows: list[dict] | None = None,
    complete: Complete | None = None,
) -> Answer:
    """The answer sentence: the LLM's if every number checks out, else the template."""
    if not verified:
        return Answer(text=None, source="unverified",
                      note=could_not_verify(plan, sql_rows or [], pandas_rows or []))
    template = Answer(text=templates.template_sentence(plan, rows), source="template")
    from app.llm import client  # imported here, never at app startup
    from app.llm.prompts import writer_messages

    ask = complete or client.complete_json
    shown = rows[:MAX_TABLE_ROWS]
    system, user = writer_messages(question, plan_summary(plan), formatted_rows(plan, shown),
                                   len(rows))
    try:
        reply = ask(system, user)
    except (client.LLMUnavailable, client.ModelOutputError) as error:
        logger.info("answer writer unavailable, using template: %s", type(error).__name__)
        return template
    sentence = reply.get("sentence") if isinstance(reply, dict) else None
    if not isinstance(sentence, str) or not sentence.strip():
        return template
    sentence = sentence.strip()
    if len(SENTENCE_END.findall(sentence)) > MAX_SENTENCES:
        logger.info("answer had more than %d sentences, using template", MAX_SENTENCES)
        return Answer(text=template.text, source="template", rejected=sentence)
    ok, unmatched = numcheck.check(sentence, numcheck.allowed_values(shown, plan, question))
    if not ok:
        numbers = [n.text for n in unmatched]
        logger.info("answer had unmatched numbers %s, using template", numbers)
        return Answer(text=template.text, source="template", unmatched=numbers, rejected=sentence)
    return Answer(text=sentence, source="llm")
