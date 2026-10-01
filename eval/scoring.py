"""The eval rubric, shared by eval.py and baseline/score_baseline.py.

Pure functions only: nothing here imports the app, so Saabit and the baseline are scored by
exactly the same rules.
"""

from __future__ import annotations

import math
import re
from typing import Any

UNITS = {"cr": 1e7, "crore": 1e7, "crores": 1e7, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5}
NUMBER = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*(cr|crores?|lakhs?|lac)?\b", re.IGNORECASE)


def match_value(got: float | None, expected: float, tolerance: float) -> bool:
    """A number is correct when it is within the absolute tolerance (plus float noise)."""
    if got is None:
        return False
    return abs(float(got) - float(expected)) <= tolerance + 1e-9


def group_key(row: dict[str, Any]) -> str:
    """The group label of a result row: every field except value and orders."""
    parts = [str(v) for k, v in row.items() if k not in ("value", "orders")]
    return " · ".join(parts)


def match_rows(got: list[dict[str, Any]], expected: dict[str, float], tolerance: float,
               ordered: bool) -> bool:
    """Grouped results. Keys compare case-insensitively; ordered means same top-N in order."""
    got_pairs = [(group_key(r).strip().lower(), r.get("value")) for r in got]
    want_pairs = [(k.strip().lower(), v) for k, v in expected.items()]
    if len(got_pairs) != len(want_pairs):
        return False
    if ordered:
        return all(gk == wk and match_value(gv, wv, tolerance)
                   for (gk, gv), (wk, wv) in zip(got_pairs, want_pairs, strict=True))
    got_map = dict(got_pairs)
    return set(got_map) == {k for k, _ in want_pairs} and all(
        match_value(got_map[k], v, tolerance) for k, v in want_pairs)


def match_refusal(status: str | None, reason: str | None, words: list[str]) -> bool:
    """A correct refusal: status unsupported and the reason names one of the words."""
    if status != "unsupported":
        return False
    text = reason or ""
    return any(re.search(rf"\b{re.escape(w)}\b", text, re.IGNORECASE) for w in words)


def has_caveat(caveats: list[str], needle: str | None) -> bool:
    """True when no caveat is required, or one caveat contains the needle."""
    if not needle:
        return True
    return any(needle.lower() in c.lower() for c in caveats)


def parse_number(text: str | None) -> float | None:
    """First number in free text: ₹, Indian commas, %, lakh and Cr understood."""
    if not text:
        return None
    match = NUMBER.search(text.replace("₹", " "))
    if match is None:
        return None
    value = float(match.group(1).replace(",", ""))
    unit = (match.group(2) or "").lower()
    return value * UNITS.get(unit, 1)


def parse_rows(text: str) -> list[dict[str, Any]]:
    """Grouped answers typed as "key=value; key=value" into result-like rows."""
    rows = []
    for part in text.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        rows.append({"key": key.strip(), "value": parse_number(value)})
    return rows


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def score_answer(question: dict[str, Any], status: str | None, reason: str | None,
                 result: list[dict[str, Any]] | None, caveats: list[str]) -> bool:
    """Is one answer correct for one questions.yaml entry? Same rule for Saabit and baseline."""
    if question["expected_status"] == "unsupported":
        return match_refusal(status, reason, question["reason_any"])
    if status != "ok" or result is None:
        return False
    expected = question["expected"]
    if isinstance(expected, dict):
        ok = match_rows(result, expected, question["tolerance"], bool(question.get("ordered")))
    else:
        ok = len(result) == 1 and match_value(result[0].get("value"), expected,
                                              question["tolerance"])
    return ok and has_caveat(caveats, question.get("caveat_contains"))


def scorecard(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals over scored rows (each has group, correct, failure, latency_s, verified_but_wrong)."""
    answerable = [r for r in rows if r["group"] != "unanswerable"]
    refusals = [r for r in rows if r["group"] == "unanswerable"]
    latencies = [r["latency_s"] for r in rows if r.get("latency_s") is not None]
    return {
        "answerable": len(answerable),
        "answerable_correct": sum(r["correct"] for r in answerable),
        "unanswerable": len(refusals),
        "refused_correctly": sum(r["correct"] for r in refusals),
        "verified_but_wrong": sum(bool(r.get("verified_but_wrong")) for r in rows),
        "verified_but_misread": sum(bool(r.get("verified_but_misread")) for r in rows),
        "plan_failures": sum(r.get("failure") == "plan" for r in rows),
        "compute_failures": sum(r.get("failure") == "compute" for r in rows),
        "p50_s": percentile(latencies, 50),
        "p95_s": percentile(latencies, 95),
    }


def pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "n/a"
