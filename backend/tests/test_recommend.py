import json
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest
import yaml

from app.core import compile_sql, evidence
from app.core.insights import build_insights
from app.core.pipeline import Workspace
from app.core.recommend import (
    WITHIN_CATEGORY_CAVEAT,
    build_recommendations,
    split_months,
)

GOLDEN = Path(__file__).resolve().parents[2] / "eval" / "golden.yaml"
CATEGORIES = ["Set", "kurta", "Top", "Western Dress"]
MONTHS = {"2022-04": 30, "2022-05": 31, "2022-06": 30}


def overview_of(cache: Path) -> dict:
    return json.loads((cache / "overview.json").read_text("utf-8"))


def rule_of(overview: dict, code: str) -> dict:
    return next(r for r in overview["rules"] if r["code"] == code)


def synthetic(
    root: Path, rates: dict[tuple[str, str], float], per_group: int = 100,
    with_fulfilment: bool = True, dataset_id: str = "abcdef012345",
    state_rates: dict[str, float] | None = None,
) -> Workspace:
    """A cleaned dataset: each (month, fulfilment) has its own cancellation rate, spread
    evenly over the four categories, one line per order."""
    rows, number = [], 0
    for month, days in MONTHS.items():
        for fulfilment in ("Amazon", "Merchant"):
            rate = rates[(month, fulfilment)]
            for category in CATEGORIES:
                for i in range(per_group):
                    number += 1
                    state = "Maharashtra"
                    if state_rates and i < 150:
                        state = "Goa"
                    cutoff = state_rates.get(state, rate) if state_rates else rate
                    rows.append({
                        "order_id": f"O{number}",
                        "order_date": date.fromisoformat(f"{month}-{1 + i % days:02d}"),
                        "status_raw": "Cancelled" if (i % 100) < cutoff * 100 else "Shipped",
                        "amount": 500.0, "qty": 1, "state": state, "category": category,
                        "sku": f"{category}-{i % 7}", "fulfilment": fulfilment,
                    })
    df = pd.DataFrame(rows)
    df["is_cancelled"] = df["status_raw"] == "Cancelled"
    if not with_fulfilment:
        df = df.drop(columns="fulfilment")
    df["order_date"] = pd.array(df["order_date"], dtype=pd.ArrowDtype(pa.date32()))
    folder = root / dataset_id
    folder.mkdir(parents=True)
    df.to_parquet(folder / "clean.parquet", index=False)
    compile_sql.create_query_db(folder)
    roles = ["order_id", "order_date", "status", "amount", "qty", "state", "category", "sku"]
    roles += ["fulfilment"] if with_fulfilment else []
    metadata = {"dataset_id": dataset_id,
                "roles": [{"role": r, "column": r} for r in roles],
                "data_check": {"partial_months": [], "rows_in": len(df), "rows_out": len(df),
                               "fixes": [], "unknown_states": []}}
    (folder / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (folder / "fixes.csv").write_text("rule,column,before,after,rows_affected\n", "utf-8")
    return Workspace(dataset_id, root, root / "no-sample-cache", folder / "cards")


def recommend(ws: Workspace) -> tuple[list[dict], list[dict]]:
    split = split_months(date(2022, 4, 1), date(2022, 6, 30), [])
    return build_recommendations(ws, split, 91)


def test_months_split_into_training_and_test_without_partial_months() -> None:
    split = split_months(date(2022, 3, 31), date(2022, 6, 29), ["2022-03"])

    assert (split.training, split.test) == (["2022-04", "2022-05"], "2022-06")
    assert split.covered_days == {"2022-03": 1, "2022-04": 30, "2022-05": 31, "2022-06": 29}
    assert split.training_range == {"start": "2022-04-01", "end": "2022-05-31"}


def test_one_full_month_is_not_enough_for_recommendations() -> None:
    split = split_months(date(2022, 4, 30), date(2022, 4, 30), [])

    assert split.test is None
    assert "at least two full months" in split.reason


def test_all_insight_cards_are_verified(real_sample_cache: Path) -> None:
    insights = overview_of(real_sample_cache)["insights"]

    assert [i["code"] for i in insights] == ["E1", "E2", "E3", "E4", "E5"]
    for item in insights:
        assert item["status"] == "ok", item
        for card_id in item["card_ids"]:
            assert evidence.load_card(real_sample_cache / "cards", card_id).verified
    e5 = insights[4]
    assert (e5["source"], e5["verified"], e5["card_ids"]) == ("fix_log", False, [])


def test_verified_appears_only_on_two_engine_results(real_sample_cache: Path) -> None:
    for item in overview_of(real_sample_cache)["insights"]:
        if item["verified"]:
            assert item["source"] == "engines" and item["card_ids"], item
            for card_id in item["card_ids"]:
                assert evidence.load_card(real_sample_cache / "cards", card_id).verified
        else:
            assert item["source"] != "engines" or item["status"] == "unverified", item


def test_partial_month_is_marked_on_the_e2_card(real_sample_cache: Path) -> None:
    e2 = overview_of(real_sample_cache)["insights"][1]

    assert "Mar 2022 (partial, 1 day) " in e2["text"]
    assert "Apr 2022 (partial" not in e2["text"]
    assert any(c.startswith("2022-03 is a partial month") for c in e2["caveats"])


def test_all_time_totals_do_not_carry_the_partial_month_note(real_sample_cache: Path) -> None:
    for item in overview_of(real_sample_cache)["insights"]:
        if item["code"] in ("E1", "E3", "E4"):
            assert not any("partial month" in c for c in item["caveats"]), item


def test_partial_month_caveat_is_on_the_e2_card(real_sample_cache: Path) -> None:
    e2 = overview_of(real_sample_cache)["insights"][1]

    card = evidence.load_card(real_sample_cache / "cards", e2["card_ids"][0])
    assert any(c.startswith("2022-03 is a partial month") for c in card.caveats)


def test_rule_decision_uses_only_training_months(tmp_path: Path) -> None:
    rates = {(m, f): 0.10 for m in MONTHS for f in ("Amazon", "Merchant")}
    rates[("2022-06", "Merchant")] = 0.40  # the gap exists only in the test month
    ws = synthetic(tmp_path, rates)

    fired, rules = recommend(ws)

    r1 = next(r for r in rules if r["code"] == "R1")
    assert r1["status"] == "not_fired"
    assert "training gap is 0.0 points" in r1["reason"]
    assert fired == [] or all(r["code"] != "R1" for r in fired)


def test_a_training_gap_that_vanishes_in_the_test_month_gets_low_confidence(
    tmp_path: Path,
) -> None:
    rates = {(m, "Amazon"): 0.10 for m in MONTHS} | {(m, "Merchant"): 0.20 for m in MONTHS}
    rates[("2022-06", "Merchant")] = 0.05
    ws = synthetic(tmp_path, rates, per_group=300)

    r1 = next(r for r in recommend(ws)[1] if r["code"] == "R1")

    assert r1["status"] == "fired"
    assert r1["confidence"] == "Low"


def test_confidence_high_when_gap_holds_in_test_month(tmp_path: Path) -> None:
    rates = {(m, "Amazon"): 0.10 for m in MONTHS} | {(m, "Merchant"): 0.20 for m in MONTHS}
    ws = synthetic(tmp_path, rates, per_group=300)  # 1,200 orders per type in June

    r1 = next(r for r in recommend(ws)[1] if r["code"] == "R1")

    assert r1["status"] == "fired"
    assert r1["confidence"] == "High"
    assert r1["backtest"]["gap"] == pytest.approx(10.0)
    assert r1["backtest"]["least_orders"] == 1200


def test_confidence_is_medium_when_test_month_is_too_small(tmp_path: Path) -> None:
    rates = {(m, "Amazon"): 0.10 for m in MONTHS} | {(m, "Merchant"): 0.20 for m in MONTHS}
    ws = synthetic(tmp_path, rates, per_group=100)  # 400 orders per type in June

    assert next(r for r in recommend(ws)[1] if r["code"] == "R1")["confidence"] == "Medium"


def test_rule_is_skipped_when_fulfilment_role_missing(tmp_path: Path) -> None:
    rates = {(m, f): 0.10 for m in MONTHS for f in ("Amazon", "Merchant")}
    ws = synthetic(tmp_path, rates, with_fulfilment=False)

    r1 = next(r for r in recommend(ws)[1] if r["code"] == "R1")
    insights = build_insights(ws, {"fixes": [], "rows_in": 1, "rows_out": 1})

    assert r1["status"] == "skipped"
    assert "fulfilment" in r1["reason"]
    assert insights[0]["status"] == "skipped" and "fulfilment" in insights[0]["reason"]


def test_state_hotspot_fires_for_a_large_state_well_above_overall(tmp_path: Path) -> None:
    rates = {(m, f): 0.10 for m in MONTHS for f in ("Amazon", "Merchant")}
    ws = synthetic(tmp_path, rates, per_group=200, state_rates={"Goa": 0.45})

    r2 = next(r for r in recommend(ws)[1] if r["code"] == "R2")

    assert r2["status"] == "fired"
    assert [s["state"] for s in r2["training"]["states"]] == ["Goa"]
    assert r2["confidence"] == "High"


def test_backtest_values_match_golden(real_sample_cache: Path) -> None:
    anchors = {a["id"]: a for a in yaml.safe_load(GOLDEN.read_text("utf-8"))["anchors"]}
    r1 = rule_of(overview_of(real_sample_cache), "R1")

    training = {r1["training"]["high"]["fulfilment"]: r1["training"]["high"]["value"],
                r1["training"]["low"]["fulfilment"]: r1["training"]["low"]["value"]}
    tested = {r1["backtest"]["high"]["fulfilment"]: r1["backtest"]["high"]["value"],
              r1["backtest"]["low"]["fulfilment"]: r1["backtest"]["low"]["value"]}
    for group, value in anchors["cancellation_by_fulfilment_apr_may"]["expected"].items():
        assert abs(training[group] - value) <= anchors["cancellation_by_fulfilment_apr_may"][
            "tolerance"]
    for group, value in anchors["cancellation_by_fulfilment_jun_backtest"]["expected"].items():
        assert abs(tested[group] - value) <= anchors["cancellation_by_fulfilment_jun_backtest"][
            "tolerance"]
    assert r1["confidence"] == "High"


def test_every_citation_points_to_an_existing_card(real_sample_cache: Path) -> None:
    overview = overview_of(real_sample_cache)
    cited = [c for item in overview["insights"] for c in item["card_ids"]]
    cited += [c for rule in overview["rules"] for c in rule["cites"]]
    cited += [r["training"]["top_skus_card"] for r in overview["rules"]
              if r["code"] == "R1" and r["status"] == "fired"]

    assert cited
    for card_id in cited:
        assert evidence.load_card(real_sample_cache / "cards", card_id).card_id == card_id


def test_impact_includes_formula_and_caveat(real_sample_cache: Path) -> None:
    r1 = rule_of(overview_of(real_sample_cache), "R1")
    impact = r1["impact"]

    assert impact["formula"].startswith("36,376 Merchant orders × 4.7-point gap ÷ 100 = about")
    assert "fewer cancellations" in impact["formula"]
    assert impact["assumption"].startswith("If Merchant-fulfilled orders were cancelled at")
    assert impact["caveat"] == WITHIN_CATEGORY_CAVEAT
    assert impact["value"] == round(36376 * r1["training"]["gap"] / 100)


def test_key_numbers_are_verified_cards(real_sample_cache: Path) -> None:
    tiles = {k["metric"]: k for k in overview_of(real_sample_cache)["key_numbers"]}

    assert list(tiles) == ["revenue", "orders", "cancellation_rate", "aov"]
    for tile in tiles.values():
        assert tile["verified"] and evidence.load_card(real_sample_cache / "cards",
                                                       tile["card_id"]).verified
    # values from the independent answer key (eval/questions.yaml s01 and s03, golden anchors)
    assert tiles["revenue"]["value"] == pytest.approx(71673394.0, abs=0.01)
    assert tiles["orders"]["value"] == 120378
    assert tiles["cancellation_rate"]["value"] == pytest.approx(14.2759, abs=0.01)
    assert tiles["aov"]["value"] == pytest.approx(694.56, abs=0.01)
