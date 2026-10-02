"""Build the E1-E5 insight cards (FR-8.2).

E1-E4 are predefined plans run through the normal pipeline, so each is a verified evidence
card (source "engines"). E5 summarises the fix log (source "fix_log"): it is never marked
Verified, because no two engines computed it. Text is written by code from the results (no
LLM), and a card whose columns the file lacks is skipped with the reason.
"""

from typing import Any

from app.core import templates
from app.core.evidence import EvidenceCard
from app.core.metrics import METRICS
from app.core.pipeline import FIXES_FILE, Workspace, partial_month_days
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
        "reason": None if verified else "The two engines disagreed on a supporting card.",
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
    shown = ", ".join(f"{name} {gap:+.1f} pts" for name, gap in gaps)
    return (f"{high} is higher than {low} in {holds} of the top {len(names)} categories "
            f"({shown}).")


def e2(ws: Workspace) -> dict[str, Any]:
    card = ws.run({"metric": "revenue", "group_by": ["month"]})
    partial = partial_month_days(ws.context().folder / FIXES_FILE)
    return insight("E2", "Monthly revenue trend", [card], month_listing(card, partial))


def month_listing(card: EvidenceCard, partial_days: dict[str, int]) -> str:
    """Revenue by month, with each partial month marked: "Mar 2022 (partial, 1 day) ₹94,810"."""
    metric = card.plan["metric"]
    parts = []
    for row in card.result:
        label = templates.key_text("month", row["month"])
        if row["month"] in partial_days:
            days = partial_days[row["month"]]
            label += f" (partial, {days} day{'' if days == 1 else 's'})"
        parts.append(f"{label} {templates.format_value(metric, row.get('value'))}")
    return f"Revenue by month: {', '.join(parts)}."


def e3(ws: Workspace) -> dict[str, Any]:
    card = ws.run({"metric": "orders", "group_by": ["state"],
                   "sort": {"by": "value", "dir": "desc"}, "limit": TOP_STATES})
    return insight("E3", f"Top {TOP_STATES} states by orders", [card], sentence(card))


def e4(ws: Workspace) -> dict[str, Any]:
    card = ws.run({"metric": "revenue", "group_by": ["category"],
                   "sort": {"by": "value", "dir": "desc"}, "limit": TOP_REVENUE_CATEGORIES})
    return insight("E4", "Top categories by revenue", [card], sentence(card))


def rows_text(count: int) -> str:
    return f"{templates.format_count(count)} row{'' if count == 1 else 's'}"


def e5(data_check: dict[str, Any]) -> dict[str, Any]:
    """Data fixes summary, from the fix log (not a plan)."""
    notes_only = ("date_order", "partial_month", "state_unknown")
    fixes = [f for f in data_check.get("fixes", []) if f["rule"] not in notes_only]
    rows_in, rows_out = data_check.get("rows_in", 0), data_check.get("rows_out", 0)
    parts = [f"{f['rule'].replace('_', ' ')} in {rows_text(f['rows_affected'])}" for f in fixes]
    text = (f"Cleaning kept {rows_text(rows_out)} of {rows_text(rows_in)}. "
            + ("Fixes: " + "; ".join(parts) + "." if parts else "No values needed fixing."))
    unknown = data_check.get("unknown_states") or []
    if unknown:
        text += f" Unknown state values kept as they are: {', '.join(unknown)}."
    partial = data_check.get("partial_months") or []
    if partial:
        text += f" Partial months: {', '.join(partial)}."
    return {"code": "E5", "title": "Data fixes", "status": "ok", "reason": None,
            "card_ids": [], "verified": False, "source": "fix_log", "caveats": [],
            "text": text}


KEY_METRICS = ("revenue", "orders", "cancellation_rate", "aov")


def key_numbers(ws: Workspace) -> list[dict[str, Any]]:
    """Whole-file totals for the workspace tiles, each a two-engine evidence card.

    A metric the file cannot support (e.g. no status column) is left out, not guessed.
    """
    tiles = []
    for metric in KEY_METRICS:
        try:
            card = ws.run({"metric": metric})
        except PlanError:
            continue
        row = card.result[0] if card.result else {}
        tiles.append({"metric": metric, "label": METRICS[metric].label,
                      "value": row.get("value"), "orders": row.get("orders"),
                      "verified": card.verified, "card_id": card.card_id})
    return tiles


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
