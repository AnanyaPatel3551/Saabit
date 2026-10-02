"""Score the manual baseline runs and print them next to Saabit's latest eval.

Reads a filled copy of baseline_template.csv (default: baseline_results.csv, falling back to the
template) and scores each filled row with the same rubric as eval.py (eval/scoring.py). Rows with
neither an answer nor a refusal are "not run" and left out of both columns, so the comparison is
always on the same questions.

Usage (from the repo root):  python eval/baseline/score_baseline.py [path/to/filled.csv]
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

import yaml

BASELINE_DIR = Path(__file__).resolve().parent
EVAL_DIR = BASELINE_DIR.parent
sys.path.insert(0, str(EVAL_DIR))

import scoring  # noqa: E402

YES = {"yes", "y", "true", "1"}


def baseline_answer(
    q: dict[str, Any], row: dict[str, str]
) -> tuple[str, str, list[dict], list[str]]:
    """A filled CSV row as (status, reason, result rows, caveats) for scoring.score_answer."""
    notes = row.get("notes", "").strip()
    if row.get("refused", "").strip().lower() in YES:
        return "unsupported", notes, [], []
    answer = row.get("answer_given", "").strip()
    if isinstance(q.get("expected"), dict):
        result = scoring.parse_rows(answer)
    else:
        result = [{"value": scoring.parse_number(answer)}]
    return "ok", "", result, [answer + " " + notes]


def is_filled(row: dict[str, str]) -> bool:
    return bool(row.get("answer_given", "").strip() or row.get("refused", "").strip())


def load_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {r["question_id"].strip(): r for r in csv.DictReader(f) if is_filled(r)}


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [r for r in rows if r["group"] != "unanswerable"]
    refusals = [r for r in rows if r["group"] == "unanswerable"]
    return {"answerable": len(answerable), "correct": sum(r["correct"] for r in answerable),
            "unanswerable": len(refusals), "refused": sum(r["correct"] for r in refusals)}


def main(argv: list[str]) -> int:
    default = BASELINE_DIR / "baseline_results.csv"
    path = Path(argv[0]) if argv else (default if default.exists()
                                        else BASELINE_DIR / "baseline_template.csv")
    questions = {q["id"]: q for q in yaml.safe_load(
        (EVAL_DIR / "questions.yaml").read_text(encoding="utf-8"))["questions"]}
    filled = load_rows(path)
    print(f"Baseline file: {path.name} · {len(filled)} of {len(questions)} questions filled")
    if not filled:
        print("Nothing to score yet: fill answer_given or refused for some rows (see README.md).")
        return 0

    latest = EVAL_DIR / "results" / "latest.json"
    saabit = {}
    if latest.exists():
        saabit = {r["id"]: r for r in json.loads(latest.read_text(encoding="utf-8"))["rows"]
                  if r["source"] == "questions"}
    base_rows, saabit_rows = [], []
    print(f"\n{'id':<5} {'group':<14} {'Saabit':<8} {'Baseline':<8} question")
    for qid, row in filled.items():
        q = questions.get(qid)
        if q is None:
            print(f"{qid:<5} unknown id, skipped")
            continue
        status, reason, result, caveats = baseline_answer(q, row)
        correct = scoring.score_answer(q, status, reason, result, caveats)
        base_rows.append({"group": q["group"], "correct": correct})
        mine = saabit.get(qid)
        if mine is not None:
            saabit_rows.append({"group": q["group"], "correct": mine["correct"]})
        mark = "—" if mine is None else ("right" if mine["correct"] else "wrong")
        print(f"{qid:<5} {q['group']:<14} {mark:<8} {'right' if correct else 'wrong':<8} "
              f"{q['question']}")

    b, s = summary(base_rows), summary(saabit_rows)
    print(f"\n{'':<24}{'Saabit':<16}Baseline")
    for label, part, whole in (("answerable correct", "correct", "answerable"),
                               ("refused correctly", "refused", "unanswerable")):
        mine, theirs = f"{s[part]}/{s[whole]}", f"{b[part]}/{b[whole]}"
        print(f"{label:<24}{mine:<16}{theirs}")
    if len(saabit_rows) < len(base_rows):
        print("\nSome questions have no Saabit result: run eval/eval.py (without --only) first.")
    write_summary(b, next(iter(filled.values())).get("notes", "").strip() or None)
    return 0


def write_summary(scores: dict[str, Any], product: str | None) -> None:
    """eval/results/baseline.json, read by the app's "How we test" page."""
    out = EVAL_DIR / "results" / "baseline.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "answerable": {"correct": scores["correct"], "total": scores["answerable"]},
        "refused": {"correct": scores["refused"], "total": scores["unanswerable"]},
        "product": product,  # the README asks for the product and model in the first row's notes
    }, indent=2), encoding="utf-8")
    print(f"Saved {out.relative_to(EVAL_DIR.parent)}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
