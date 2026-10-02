"""Build the E1-E5 insight cards (FR-8.2).

E1-E4 are predefined plans run through the normal pipeline, so each is a verified evidence
card (source "engines"). E5 summarises the fix log (source "fix_log"): it is never marked
Verified, because no two engines computed it. Text is written by code from the results (no
LLM), and a card whose columns the file lacks is skipped with the reason.
"""

from datetime import date
from typing import Any

from app.core import templates
from app.core.coverage import MonthCoverage, partial_coverage
from app.core.evidence import EvidenceCard
from app.core.pipeline import Workspace, partial_months_of
from app.core.plan import Plan, PlanError

TOP_CATEGORIES = 4  # FR-8.2: E1 within each of the top 4 categories
TOP_STATES = 10
TOP_REVENUE_CATEGORIES = 5


def insight(code: str, title: str, cards: list[EvidenceCard], text: str) -> dict[str, Any]:
    """A card computed by both engines; its evidence cards' caveats travel with it."""
    verified = all(card.verified for card in cards)
    return {
        "code": code,
        "title": title,
        "status": "ok" if verified else "unverified",
        "reason": None if verified else ("One of the numbers behind this could not be "
                                         "double-checked, so it is not shown."),
        "card_ids": [card.card_id for card in cards],
        "verified": verified,
        "source": "engines",
        "caveats": insight_caveats(cards),
        "text": text,
    }


def insight_caveats(cards: list[EvidenceCard]) -> list[str]:
    """The cards' caveats, once each (the engines already leave the partial-month note off
    all-time totals)."""
    return list(dict.fromkeys(c for card in cards for c in card.caveats))


def skipped(code: str, title: str, reason: str) -> dict[str, Any]:
    return {"code": code, "title": title, "status": "skipped", "reason": reason,
            "card_ids": [], "verified": False, "source": None, "caveats": [], "text": None}


def sentence(card: EvidenceCard) -> str:
    return templates.template_sentence(Plan.model_validate(card.plan), card.result)


def e1(ws: Workspace) -> dict[str, Any]:
    """Cancellation by fulfilment, overall and within each of the top 4 categories by orders."""
    title = "Cancellation rate by fulfilment"
    overall = ws.run({"metric": "cancellation_rate", "group_by": ["fulfilment"]})
    try:
        top = ws.run({"metric": "orders", "group_by": ["category"],
                      "sort": {"by": "value", "dir": "desc"}, "limit": TOP_CATEGORIES})
    except PlanError:
        return insight("E1", title, [overall], sentence(overall) + " (No category column, so "
                       "the within-category check is not available.)")
    names = [row["category"] for row in top.result]
    within = ws.run({"metric": "cancellation_rate", "group_by": ["category", "fulfilment"],
                     "filters": [{"column": "category", "op": "in", "values": names}]})
    return insight("E1", title, [overall, top, within],
                   sentence(overall) + " " + within_text(overall, within, names))


def within_text(overall: EvidenceCard, within: EvidenceCard, names: list[str]) -> str:
    """Whether the overall gap keeps its sign inside each top category."""
    rates = {row["fulfilment"]: row["value"] for row in overall.result if row["value"] is not None}
    if len(rates) < 2:
        return ""
    high, low = max(rates, key=lambda k: rates[k]), min(rates, key=lambda k: rates[k])
    gaps = []
    for name in names:
        cells = {r["fulfilment"]: r["value"] for r in within.result if r["category"] == name}
        if high in cells and low in cells:
            gaps.append((name, cells[high] - cells[low]))
    holds = sum(gap > 0 for _, gap in gaps)
    shown = ", ".join(f"{name} {gap:+.1f} percentage points" for name, gap in gaps)
    return (f"{high} is higher than {low} in {holds} of the top {len(names)} categories "
            f"({shown}).")


def e2(ws: Workspace) -> dict[str, Any]:
    card = ws.run({"metric": "revenue", "group_by": ["month"]})
    partial = partial_months_of(ws.context())
    return insight("E2", "Monthly revenue trend", [card], month_listing(card, partial))


def month_listing(card: EvidenceCard, partial: dict[str, MonthCoverage]) -> str:
    """Revenue by month in the answers' style, each partial month marked with its days:
    "Mar 2022 (only 1 day of data, 31 Mar) ₹94,810, Apr 2022 ₹2.62 Cr, ..."."""
    return templates.template_sentence(Plan.model_validate(card.plan), card.result, partial)


def e3(ws: Workspace) -> dict[str, Any]:
    card = ws.run({"metric": "orders", "group_by": ["state"],
                   "sort": {"by": "value", "dir": "desc"}, "limit": TOP_STATES})
    return insight("E3", f"Top {TOP_STATES} states by orders", [card], sentence(card))


def e4(ws: Workspace) -> dict[str, Any]:
    card = ws.run({"metric": "revenue", "group_by": ["category"],
                   "sort": {"by": "value", "dir": "desc"}, "limit": TOP_REVENUE_CATEGORIES})
    return insight("E4", "Top categories by revenue", [card], sentence(card))


def rows_text(count: int) -> str:
    return templates.plural(count, "row")


def parse_day(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def partial_note(data_check: dict[str, Any]) -> str:
    """'Mar 2022 has only 1 day of data; Jun 2022 has 29 of 30 days of data (missing 30 Jun).'
    The same edge-based months as the answers and the "Good to know" list."""
    partial = partial_coverage(parse_day(data_check.get("date_min")),
                               parse_day(data_check.get("date_max")))
    if not partial:
        return ""
    return "; ".join(f"{c.label} has {c.sentence_note()}" for _, c in sorted(partial.items()))


def e5(data_check: dict[str, Any]) -> dict[str, Any]:
    """Data fixes summary, from the fix log (not a plan)."""
    notes_only = ("date_order", "partial_month", "state_unknown")
    fixes = [f for f in data_check.get("fixes", []) if f["rule"] not in notes_only]
    rows_in, rows_out = data_check.get("rows_in", 0), data_check.get("rows_out", 0)
    parts = [templates.clean_up_text(f["rule"], f.get("entries", 0), f["rows_affected"])
             for f in fixes]
    text = (f"Cleaning kept {rows_text(rows_out)} of {rows_text(rows_in)}. "
            + ("What we cleaned up: " + "; ".join(parts) + "." if parts
               else "Nothing needed cleaning."))
    unknown = data_check.get("unknown_states") or []
    if unknown:
        text += f" State names we didn't recognise, kept as written: {', '.join(unknown)}."
    note = partial_note(data_check)
    if note:
        text += f" Good to know: {note}."
    return {"code": "E5", "title": "Data fixes", "status": "ok", "reason": None,
            "card_ids": [], "verified": False, "source": "fix_log", "caveats": [],
            "text": text}


def build_insights(ws: Workspace, data_check: dict[str, Any]) -> list[dict[str, Any]]:
    """E1-E5. A card the file cannot support is skipped with the reason."""
    titles = {"E1": "Cancellation rate by fulfilment", "E2": "Monthly revenue trend",
              "E3": f"Top {TOP_STATES} states by orders", "E4": "Top categories by revenue"}
    cards = []
    for code, build in (("E1", e1), ("E2", e2), ("E3", e3), ("E4", e4)):
        try:
            cards.append(build(ws))
        except PlanError as error:
            cards.append(skipped(code, titles[code], error.message))
    cards.append(e5(data_check))
    return cards
