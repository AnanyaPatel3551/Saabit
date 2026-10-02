"""Recommendation rules, backtest and confidence (FR-8.3 to FR-8.5, D8, D14).

Every rule decides using training months only. The last full month is held out and used once,
to backtest a rule that fired; confidence comes from that backtest, never from a model. All
numbers come from verified evidence cards, and every recommendation cites them.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.core import templates
from app.core.evidence import EvidenceCard
from app.core.pipeline import Workspace
from app.core.plan import PlanError

# R1 (FR-8.3, FR-8.4)
GAP_POINTS = 3.0
HIGH_MIN_ORDERS = 1000
TOP_CATEGORIES = 4
TOP_SKUS = 10
# R2
HOTSPOT_MIN_ORDERS = 500
HOTSPOT_POINTS = 5.0
HOTSPOT_TEST_MIN_ORDERS = 250
# R3
DECLINE_HIGH = 0.05
LISTED = 5

CONFIDENCE_ORDER = {"Low": 0, "Medium": 1, "High": 2}
WITHIN_CATEGORY_CAVEAT = ("The within-category check reduces, but does not rule out, other "
                          "causes such as courier, region or SKU mix inside a category.")
ASSOCIATION_CAVEAT = "This is an association in past data, not proof of what caused it."


@dataclass(frozen=True)
class MonthSplit:
    """Training months decide; the test month (last full month) only backtests."""

    training: list[str]
    test: str | None
    covered_days: dict[str, int] = field(default_factory=dict)  # days of data per month
    reason: str | None = None

    def range_of(self, months: list[str]) -> dict[str, str]:
        return {"start": month_start(months[0]).isoformat(),
                "end": month_end(months[-1]).isoformat()}

    @property
    def training_range(self) -> dict[str, str]:
        return self.range_of(self.training)

    @property
    def test_range(self) -> dict[str, str]:
        return self.range_of([self.test or ""])

    @property
    def training_label(self) -> str:
        first, last = label(self.training[0]), label(self.training[-1])
        return first if first == last else f"{first.split()[0]}–{last}"


def month_start(month: str) -> date:
    return date.fromisoformat(f"{month}-01")


def month_end(month: str) -> date:
    first = month_start(month)
    return (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def label(month: str) -> str:
    return month_start(month).strftime("%b %Y")


def split_months(date_min: date, date_max: date, partial_months: list[str]) -> MonthSplit:
    """Full months in the data (partial ones excluded); last is the test month."""
    months, covered = [], {}
    cursor = date_min.replace(day=1)
    while cursor <= date_max:
        key = cursor.strftime("%Y-%m")
        start, end = max(cursor, date_min), min(month_end(key), date_max)
        months.append(key)
        covered[key] = (end - start).days + 1
        cursor = month_end(key) + timedelta(days=1)
    full = [m for m in months if m not in partial_months]
    if len(full) < 2:
        return MonthSplit([], None, covered, "Recommendations need at least two full months: "
                          "one or more to learn from and one to test on.")
    return MonthSplit(full[:-1], full[-1], covered)


def rule(code: str, title: str, status: str, reason: str | None = None,
         cards: list[EvidenceCard] | None = None, **details: Any) -> dict[str, Any]:
    return {"code": code, "title": title, "status": status, "reason": reason,
            "cites": [c.card_id for c in cards or []], "text": None, "training": None,
            "backtest": None, "confidence": None, "impact": None, **details}


def unverified(cards: list[EvidenceCard]) -> bool:
    return not all(card.verified for card in cards)


def by_key(card: EvidenceCard, key: str) -> dict[str, dict]:
    return {row[key]: row for row in card.result if row.get(key) is not None}


def about(value: float) -> str:
    """A rounded estimate: nearest 100 from 1,000 up, nearest 10 below."""
    step = 100 if abs(value) >= 1000 else 10
    return templates.format_count(round(value / step) * step)


def r1_fulfilment_gap(ws: Workspace, split: MonthSplit, days: int) -> dict[str, Any]:
    code, title = "R1", "Fulfilment cancellation gap"
    train = ws.run({"metric": "cancellation_rate", "group_by": ["fulfilment"],
                    "date_range": split.training_range})
    rates = {k: r for k, r in by_key(train, "fulfilment").items() if r["value"] is not None}
    if len(rates) < 2:
        return rule(code, title, "not_fired", "Needs at least two fulfilment types.", [train])
    high = max(rates, key=lambda k: rates[k]["value"])
    low = min(rates, key=lambda k: rates[k]["value"])
    gap = rates[high]["value"] - rates[low]["value"]
    if gap < GAP_POINTS:
        return rule(code, title, "not_fired", f"The training gap is {gap:.1f} percentage "
                    f"points, under {GAP_POINTS:g}.", [train])
    try:
        top = ws.run({"metric": "orders", "group_by": ["category"],
                      "date_range": split.training_range,
                      "sort": {"by": "value", "dir": "desc"}, "limit": TOP_CATEGORIES})
    except PlanError:
        return rule(code, title, "skipped", "Needs a category column for the "
                    "within-category check.", [train])
    names = list(by_key(top, "category"))
    within = ws.run({"metric": "cancellation_rate", "group_by": ["category", "fulfilment"],
                     "filters": [{"column": "category", "op": "in", "values": names}],
                     "date_range": split.training_range})
    category_gaps = []
    for name in names:
        cells = {r["fulfilment"]: r["value"] for r in within.result if r["category"] == name}
        if cells.get(high) is None or cells.get(low) is None:
            return rule(code, title, "not_fired", f"{name} does not have both {high} and "
                        f"{low} orders, so the within-category check cannot pass.",
                        [train, top, within])
        category_gaps.append({"category": name, "gap": cells[high] - cells[low]})
    reversed_in = [g["category"] for g in category_gaps if g["gap"] <= 0]
    if reversed_in:
        return rule(code, title, "not_fired", f"The gap does not hold in {', '.join(reversed_in)}.",
                    [train, top, within])
    skus = ws.run({"metric": "cancelled_orders", "group_by": ["sku"],
                   "filters": [{"column": "fulfilment", "values": [high]}],
                   "date_range": split.training_range,
                   "sort": {"by": "value", "dir": "desc"}, "limit": TOP_SKUS})
    test = ws.run({"metric": "cancellation_rate", "group_by": ["fulfilment"],
                   "date_range": split.test_range})
    totals = ws.run({"metric": "orders", "group_by": ["fulfilment"]})
    cards = [train, top, within, skus, test, totals]
    if unverified(cards):
        return rule(code, title, "skipped", "A supporting card could not be verified.", cards)

    tested = by_key(test, "fulfilment")
    high_test, low_test = tested.get(high, {}), tested.get(low, {})
    test_gap = None
    if high_test.get("value") is not None and low_test.get("value") is not None:
        test_gap = high_test["value"] - low_test["value"]
    least_orders = min(high_test.get("orders", 0), low_test.get("orders", 0))
    if test_gap is not None and test_gap > 0 and test_gap >= GAP_POINTS \
            and least_orders >= HIGH_MIN_ORDERS:
        confidence = "High"
    elif test_gap is not None and test_gap > 0:
        confidence = "Medium"
    else:
        confidence = "Low"

    high_orders = by_key(totals, "fulfilment")[high]["orders"]
    estimate = high_orders * gap / 100
    result = rule(code, title, "fired", None, cards)
    result.update(
        text=(f"{high}-fulfilled orders were cancelled more often than {low}-fulfilled ones in "
              f"{split.training_label} ({templates.format_pct(rates[high]['value'])} vs "
              f"{templates.format_pct(rates[low]['value'])}, a {gap:.1f}-percentage-point gap), "
              f"and the gap held in each of the top {len(names)} categories. Test moving the "
              f"top {high} products (SKUs) by cancelled orders to {low} fulfilment."),
        training={"months": split.training, "high": {"fulfilment": high, **rates[high]},
                  "low": {"fulfilment": low, **rates[low]}, "gap": gap,
                  "categories": category_gaps, "top_skus_card": skus.card_id},
        backtest={"month": split.test, "high": tested.get(high), "low": tested.get(low),
                  "gap": test_gap, "holds": test_gap is not None and test_gap > 0,
                  "least_orders": least_orders},
        confidence=confidence,
        confidence_reason=confidence_note(confidence, test_gap, least_orders, split.test or ""),
        impact={
            "value": round(estimate),
            "formula": (f"{templates.format_count(high_orders)} {high} orders × "
                        f"{gap:.1f}-percentage-point gap ÷ 100 = about {about(estimate)} fewer "
                        f"cancellations over the {days} days of data"),
            "assumption": (f"If {high}-fulfilled orders were cancelled at {low}'s training rate "
                           f"({templates.format_pct(rates[low]['value'])})."),
            "caveat": WITHIN_CATEGORY_CAVEAT,
        },
    )
    return result


def confidence_note(level: str, test_gap: float | None, least: int, month: str) -> str:
    if test_gap is None:
        return f"Low: {label(month)} does not have both fulfilment types to test on."
    if level == "High":
        return (f"High: in {label(month)} the gap kept its sign at {test_gap:.1f} percentage "
                f"points, with at least {templates.format_count(least)} orders per group.")
    if level == "Medium":
        return (f"Medium: the gap kept its sign in {label(month)} ({test_gap:.1f} percentage "
                f"points) but was under {GAP_POINTS:g} percentage points or had under "
                f"{templates.format_count(HIGH_MIN_ORDERS)} orders per group.")
    return f"Low: the gap reversed in {label(month)} ({test_gap:.1f} percentage points)."


def weakest(levels: list[str]) -> str:
    return min(levels, key=lambda level: CONFIDENCE_ORDER[level])


def r2_state_hotspot(ws: Workspace, split: MonthSplit) -> dict[str, Any]:
    code, title = "R2", "State cancellation hotspots"
    overall = ws.run({"metric": "cancellation_rate", "date_range": split.training_range})
    states = ws.run({"metric": "cancellation_rate", "group_by": ["state"],
                     "date_range": split.training_range})
    base = overall.result[0]["value"] if overall.result else None
    if base is None:
        return rule(code, title, "not_fired", "No orders in the training months.", [overall])
    hot = sorted((r for r in states.result if r["value"] is not None
                  and r["orders"] >= HOTSPOT_MIN_ORDERS and r["value"] - base >= HOTSPOT_POINTS),
                 key=lambda r: r["value"] - base, reverse=True)[:LISTED]
    if not hot:
        return rule(code, title, "not_fired", f"No state with at least {HOTSPOT_MIN_ORDERS} "
                    f"orders is {HOTSPOT_POINTS:g} or more percentage points above the overall "
                    f"{templates.format_pct(base)}.", [overall, states])
    names = [r["state"] for r in hot]
    test_overall = ws.run({"metric": "cancellation_rate", "date_range": split.test_range})
    test_states = ws.run({"metric": "cancellation_rate", "group_by": ["state"],
                          "filters": [{"column": "state", "op": "in", "values": names}],
                          "date_range": split.test_range})
    cards = [overall, states, test_overall, test_states]
    if unverified(cards):
        return rule(code, title, "skipped", "A supporting card could not be verified.", cards)
    test_base = test_overall.result[0]["value"] if test_overall.result else None
    tested = by_key(test_states, "state")
    checks = []
    for row in hot:
        t = tested.get(row["state"])
        gap = None
        if t is not None and t["value"] is not None and test_base is not None:
            gap = t["value"] - test_base
        if gap is not None and gap >= HOTSPOT_POINTS and t["orders"] >= HOTSPOT_TEST_MIN_ORDERS:
            level = "High"
        elif gap is not None and gap > 0:
            level = "Medium"
        else:
            level = "Low"
        checks.append({"state": row["state"], "test_gap": gap,
                       "test_orders": t["orders"] if t else 0, "confidence": level})
    excess = sum(r["orders"] * (r["value"] - base) / 100 for r in hot)
    details = ", ".join(f"{r['state']} {templates.format_pct(r['value'])}" for r in hot)
    result = rule(code, title, "fired", None, cards)
    result.update(
        text=(f"In {split.training_label}, orders shipped to {', '.join(names)} were cancelled at "
              f"least {HOTSPOT_POINTS:g} percentage points more often than the "
              f"{templates.format_pct(base)} overall rate ({details}). Look into delivery and "
              f"address problems for these states."),
        training={"months": split.training, "overall": base, "states": hot},
        backtest={"month": split.test, "overall": test_base, "states": checks},
        confidence=weakest([c["confidence"] for c in checks]),
        confidence_reason="The weakest state's backtest sets the confidence.",
        impact={
            "value": round(excess),
            "formula": "Σ state orders × (state rate − overall rate) ÷ 100 = about "
                       f"{about(excess)} extra cancellations in {split.training_label}",
            "assumption": "If these states were cancelled at the overall rate.",
            "caveat": ASSOCIATION_CAVEAT,
        },
    )
    return result


def r3_declining_category(ws: Workspace, split: MonthSplit) -> dict[str, Any]:
    code, title = "R3", "Declining categories"
    if len(split.training) < 2:
        return rule(code, title, "skipped", "Needs at least two full training months to see a "
                    "decline.")
    card = ws.run({"metric": "revenue", "group_by": ["category", "month"],
                   "date_range": split.training_range})
    daily: dict[str, dict[str, float]] = {}
    for row in card.result:
        if row["value"] is not None:
            days = split.covered_days[row["month"]]
            daily.setdefault(row["category"], {})[row["month"]] = row["value"] / days
    falling = []
    for name, months in daily.items():
        series = [months.get(m) for m in split.training]
        if None not in series and all(a > b for a, b in zip(series, series[1:], strict=False)):
            falling.append((name, series))
    if not falling:
        return rule(code, title, "not_fired", "No category's revenue per day fell in every "
                    "training month.", [card])
    falling.sort(key=lambda item: item[1][0] - item[1][-1], reverse=True)
    falling = falling[:LISTED]
    names = [name for name, _ in falling]
    test = ws.run({"metric": "revenue", "group_by": ["category"],
                   "filters": [{"column": "category", "op": "in", "values": names}],
                   "date_range": split.test_range})
    cards = [card, test]
    if unverified(cards):
        return rule(code, title, "skipped", "A supporting card could not be verified.", cards)
    test_days = split.covered_days[split.test or ""]
    tested = by_key(test, "category")
    checks = []
    for name, series in falling:
        t = tested.get(name)
        change = None
        if t is not None and t["value"] is not None:
            change = (t["value"] / test_days) / series[-1] - 1
        level = ("High" if change is not None and change <= -DECLINE_HIGH
                 else "Medium" if change is not None and change < 0 else "Low")
        checks.append({"category": name, "test_change": change, "confidence": level})
    lost = sum((series[0] - series[-1]) * test_days for _, series in falling)
    details = ", ".join(f"{name} {templates.display_inr(series[0])} → "
                        f"{templates.display_inr(series[-1])} a day" for name, series in falling)
    result = rule(code, title, "fired", None, cards)
    result.update(
        text=(f"Revenue per day fell in every training month for {', '.join(names)} "
              f"({details}). Review stock, pricing and listings for these categories."),
        training={"months": split.training, "daily_revenue": {n: s for n, s in falling}},
        backtest={"month": split.test, "categories": checks},
        confidence=weakest([c["confidence"] for c in checks]),
        confidence_reason="Per category: High if revenue per day fell at least 5% again in the "
                          "test month, Medium if it fell, Low if it rose; the weakest sets this.",
        impact={
            "value": round(lost),
            "formula": f"Σ (first − last training revenue per day) × {test_days} days = about "
                       f"{templates.display_inr(round(lost / 1000) * 1000)} less revenue a month",
            "assumption": "If revenue per day stays at the last training month's level.",
            "caveat": ASSOCIATION_CAVEAT,
        },
    )
    return result


def build_recommendations(
    ws: Workspace, split: MonthSplit, days: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(fired recommendations, every rule with its status). Rules use training months only."""
    if split.test is None:
        reason = split.reason or "Not enough full months."
        rules = [rule(c, t, "skipped", reason) for c, t in
                 (("R1", "Fulfilment cancellation gap"), ("R2", "State cancellation hotspots"),
                  ("R3", "Declining categories"))]
        return [], rules
    rules = []
    for code, title, build in (("R1", "Fulfilment cancellation gap",
                                lambda: r1_fulfilment_gap(ws, split, days)),
                               ("R2", "State cancellation hotspots",
                                lambda: r2_state_hotspot(ws, split)),
                               ("R3", "Declining categories",
                                lambda: r3_declining_category(ws, split))):
        try:
            rules.append(build())
        except PlanError as error:
            rules.append(rule(code, title, "skipped", error.message))
    fired = [r for r in rules if r["status"] == "fired"]
    fired.sort(key=lambda r: (-CONFIDENCE_ORDER[r["confidence"]], -abs(r["impact"]["value"])))
    return fired, rules
