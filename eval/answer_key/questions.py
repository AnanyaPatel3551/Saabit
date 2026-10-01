"""Answer key for the 50 eval questions (PRD "Evaluation plan").

Plain pandas on the raw sample file. It never imports the app, so the app cannot pass by sharing
a bug with it. The cleaning rules are the ones in notebooks/golden_answers.ipynb:

- headers stripped; dates parsed with the fixed format %m-%d-%y;
- an order is cancelled if ANY of its lines has Status exactly "Cancelled";
- states mapped with the hand-written dictionary below; unknown spellings left out of state groups;
- orders are distinct Order IDs; revenue and units count only lines of orders that are not cancelled;
- aov is revenue divided by distinct orders that are not cancelled.

Each question carries the plan it should be read as. This file evaluates that plan itself, then
writes eval/questions.yaml. Run from the repo root:  python eval/answer_key/questions.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = ROOT / "data" / "sample" / "amazon_sale_report.csv"
OUT_PATH = ROOT / "eval" / "questions.yaml"

STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
    "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan",
    "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
]
UNION_TERRITORIES = [
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]
VARIANTS = {
    "rj": "Rajasthan", "rajsthan": "Rajasthan", "rajshthan": "Rajasthan", "orissa": "Odisha",
    "pondicherry": "Puducherry", "new delhi": "Delhi", "nl": "Nagaland", "pb": "Punjab",
    "ar": "Arunachal Pradesh", "punjab/mohali/zirakpur": "Punjab",
    "jammu & kashmir": "Jammu and Kashmir", "andaman & nicobar": "Andaman and Nicobar Islands",
    "dadra and nagar": "Dadra and Nagar Haveli and Daman and Diu",
}
LOOKUP = {name.lower(): name for name in STATES + UNION_TERRITORIES} | VARIANTS

# Plan column -> raw/derived column in the frame built by load().
COLUMNS = {"state": "state", "category": "Category", "fulfilment": "Fulfilment",
           "channel": "Sales Channel", "sku": "SKU", "month": "month"}
TOLERANCE = {"orders": 0, "units": 0, "revenue": 0.01, "aov": 0.01, "cancellation_rate": 0.01}
DECIMALS = {"orders": 0, "units": 0, "revenue": 2, "aov": 2, "cancellation_rate": 4}

APR_JUN = {"start": "2022-04-01", "end": "2022-06-30"}


def month(m: str) -> dict:
    """Inclusive date range for one month of 2022, e.g. month("05")."""
    end = pd.Period(f"2022-{m}", freq="M").end_time.date().isoformat()
    return {"start": f"2022-{m}-01", "end": end}


def plan(metric: str, group_by: list[str] | None = None, filters: dict | None = None,
         date_range: dict | None = None, top: int | None = None) -> dict:
    """A PRD plan. filters is {column: value}; top N sorts by value descending."""
    out: dict = {"status": "ok", "metric": metric, "group_by": group_by or [],
                 "filters": [{"column": c, "op": "eq", "values": [v]}
                             for c, v in (filters or {}).items()]}
    if date_range:
        out["date_range"] = date_range
    if group_by == ["month"]:
        out["sort"] = {"by": "key", "dir": "asc"}
    if top:
        out["sort"] = {"by": "value", "dir": "desc"}
        out["limit"] = top
    return out


def ok(qid: str, question: str, group: str, the_plan: dict, caveat: str | None = None) -> dict:
    return {"id": qid, "question": question, "group": group, "plan": the_plan, "caveat": caveat}


def refuse(qid: str, question: str, reason_any: list[str]) -> dict:
    return {"id": qid, "question": question, "group": "unanswerable", "reason_any": reason_any}


QUESTIONS: list[dict] = [
    # Single metric (12)
    ok("s01", "What is the total revenue across all months?", "single_metric", plan("revenue")),
    ok("s02", "How many units were sold in June 2022?", "single_metric", plan("units", date_range=month("06"))),
    ok("s03", "What is the average order value overall?", "single_metric", plan("aov")),
    ok("s04", "AOV in May 2022", "single_metric", plan("aov", date_range=month("05"))),
    ok("s05", "kitna revenue aaya Amazon fulfilment se?", "single_metric",
       plan("revenue", filters={"fulfilment": "Amazon"})),
    ok("s06", "How many orders were fulfilled by the merchant?", "single_metric",
       plan("orders", filters={"fulfilment": "Merchant"})),
    ok("s07", "What is the cancellation rate for kurta?", "single_metric",
       plan("cancellation_rate", filters={"category": "kurta"})),
    ok("s08", "revenue from karnataka in may", "single_metric",
       plan("revenue", filters={"state": "Karnataka"}, date_range=month("05"))),
    ok("s09", "How many orders came through the Non-Amazon channel?", "single_metric",
       plan("orders", filters={"channel": "Non-Amazon"})),
    ok("s10", "Total units sold", "single_metric", plan("units")),
    ok("s11", "What was the cancellation rate in June 2022?", "single_metric",
       plan("cancellation_rate", date_range=month("06"))),
    ok("s12", "Western Dress ki total sales kitni hai", "single_metric",
       plan("revenue", filters={"category": "Western Dress"})),

    # Breakdowns (10)
    ok("b01", "Top 5 states by orders", "breakdown", plan("orders", ["state"], top=5)),
    ok("b02", "Revenue by category", "breakdown", plan("revenue", ["category"])),
    ok("b03", "How many orders by fulfilment type?", "breakdown", plan("orders", ["fulfilment"])),
    ok("b04", "Top 3 categories by units sold", "breakdown", plan("units", ["category"], top=3)),
    ok("b05", "top 5 skus by unit sold", "breakdown", plan("units", ["sku"], top=5)),
    ok("b06", "Average order value by fulfilment", "breakdown", plan("aov", ["fulfilment"])),
    ok("b07", "Revenue by sales channel", "breakdown", plan("revenue", ["channel"])),
    ok("b08", "Cancellation rate by category", "breakdown", plan("cancellation_rate", ["category"])),
    ok("b09", "top 5 states by revenue", "breakdown", plan("revenue", ["state"], top=5)),
    ok("b10", "sabse zyada orders kis category mein hain", "breakdown",
       plan("orders", ["category"], top=1)),

    # Trends and comparisons (8)
    ok("t01", "Monthly revenue from April to June 2022", "trend",
       plan("revenue", ["month"], date_range=APR_JUN)),
    ok("t02", "monthly orders apr to jun", "trend", plan("orders", ["month"], date_range=APR_JUN)),
    ok("t03", "How did the cancellation rate change month by month from April to June 2022?", "trend",
       plan("cancellation_rate", ["month"], date_range=APR_JUN)),
    ok("t04", "Amazon vs Merchant cancellation rate in May 2022", "trend",
       plan("cancellation_rate", ["fulfilment"], date_range=month("05"))),
    ok("t05", "Compare revenue in April and May 2022", "trend",
       plan("revenue", ["month"], date_range={"start": "2022-04-01", "end": "2022-05-31"})),
    ok("t06", "AOV trend by month, April to June 2022", "trend",
       plan("aov", ["month"], date_range=APR_JUN)),
    ok("t07", "Set category revenue month by month, Apr-Jun 2022", "trend",
       plan("revenue", ["month"], filters={"category": "Set"}, date_range=APR_JUN)),
    ok("t08", "merchant orders har mahine april se june", "trend",
       plan("orders", ["month"], filters={"fulfilment": "Merchant"}, date_range=APR_JUN)),

    # Trap questions (10)
    ok("x01", "rajsthan ka cancellation kitna hai", "trap",
       plan("cancellation_rate", filters={"state": "Rajasthan"})),
    ok("x02", "How many orders were placed in March 2022?", "trap",
       plan("orders", date_range=month("03")), caveat="partial"),
    ok("x03", "Revenue in March 2022", "trap", plan("revenue", date_range=month("03")), caveat="partial"),
    ok("x04", "RJ se kitne orders aaye", "trap", plan("orders", filters={"state": "Rajasthan"})),
    ok("x05", "orders from orissa", "trap", plan("orders", filters={"state": "Odisha"})),
    ok("x06", "Pondicherry revenue", "trap", plan("revenue", filters={"state": "Puducherry"})),
    ok("x07", "How many orders from New Delhi?", "trap", plan("orders", filters={"state": "Delhi"})),
    ok("x08", "april mein total orders kitne the", "trap", plan("orders", date_range=month("04"))),
    ok("x09", "Units sold in April 2022", "trap", plan("units", date_range=month("04"))),
    ok("x10", "Monthly revenue trend", "trap", plan("revenue", ["month"]), caveat="partial"),

    # Unanswerable (10): reason_any words, matched as whole words, case-insensitive
    refuse("u01", "What is the profit margin by category?", ["cost"]),
    refuse("u02", "What share of orders were cash on delivery?", ["payment", "COD", "cash"]),
    refuse("u03", "forcast next month sales", ["forecast", "forecasting", "predict", "future"]),
    refuse("u04", "How many repeat customers do I have?", ["customer", "customers"]),
    refuse("u05", "What is the return on my ad spend?", ["ad", "ads", "advertising", "spend", "marketing"]),
    refuse("u06", "What is the average delivery time by state?", ["delivery", "time", "timestamp"]),
    refuse("u07", "How much inventory is left for each SKU?", ["inventory", "stock"]),
    refuse("u08", "kaunsi age group ke customers sabse zyada khareedte hain",
           ["age", "customer", "customers", "demographic", "demographics"]),
    refuse("u09", "How much did returns cost me in May 2022?", ["cost", "costs"]),
    refuse("u10", "profit kitna hua june mein", ["cost", "costs"]),
]


def load(path: Path = CSV_PATH, drop_duplicate_lines: bool = False) -> pd.DataFrame:
    """The raw file with the notebook's cleaning rules applied."""
    df = pd.read_csv(path, low_memory=False)
    df.columns = df.columns.str.strip()
    if drop_duplicate_lines:
        df = df.drop_duplicates(subset=[c for c in df.columns if c != "index"])
    df["order_date"] = pd.to_datetime(df["Date"], format="%m-%d-%y")
    df["month"] = df["order_date"].dt.strftime("%Y-%m")
    cancelled = (df["Status"] == "Cancelled").groupby(df["Order ID"]).any()
    df["order_cancelled"] = df["Order ID"].map(cancelled)
    df["state"] = df["ship-state"].str.strip().str.lower().map(LOOKUP)
    return df


def metric_value(metric: str, rows: pd.DataFrame) -> float:
    """One metric over a set of lines, by the PRD definitions."""
    kept = rows[~rows["order_cancelled"]]
    if metric == "orders":
        return float(rows["Order ID"].nunique())
    if metric == "revenue":
        return float(kept["Amount"].sum())
    if metric == "units":
        return float(kept["Qty"].sum())
    if metric == "aov":
        return float(kept["Amount"].sum()) / kept["Order ID"].nunique()
    if metric == "cancellation_rate":
        ids = rows.drop_duplicates("Order ID")
        return 100 * float(ids["order_cancelled"].sum()) / len(ids)
    raise ValueError(metric)


def rounded(value: float, digits: int) -> float | int:
    """Counts as whole numbers, money to 2 places, rates to 4."""
    return int(round(value)) if digits == 0 else round(value, digits)


def evaluate(the_plan: dict, df: pd.DataFrame) -> float | dict[str, float]:
    """Apply a plan: filters, inclusive dates, optional grouping, sort and limit."""
    rows = df
    for f in the_plan["filters"]:
        rows = rows[rows[COLUMNS[f["column"]]].isin(f["values"])]
    if "date_range" in the_plan:
        start, end = the_plan["date_range"]["start"], the_plan["date_range"]["end"]
        rows = rows[(rows["order_date"] >= start) & (rows["order_date"] <= end)]
    metric = the_plan["metric"]
    digits = DECIMALS[metric]
    if not the_plan["group_by"]:
        return rounded(metric_value(metric, rows), digits)
    (dim,) = the_plan["group_by"]
    column = COLUMNS[dim]
    values = {str(key): rounded(metric_value(metric, part), digits)
              for key, part in rows.dropna(subset=[column]).groupby(column)}
    limit = the_plan.get("limit")
    if limit:
        ranked = sorted(values.items(), key=lambda kv: -kv[1])
        if len(ranked) > limit and ranked[limit - 1][1] == ranked[limit][1]:
            raise AssertionError(f"tie at the top-{limit} cut-off: {ranked[limit - 1:limit + 1]}")
        return dict(ranked[:limit])
    return dict(sorted(values.items()))


def entry(q: dict, df: pd.DataFrame) -> dict:
    """One questions.yaml entry."""
    if q["group"] == "unanswerable":
        return {"id": q["id"], "question": q["question"], "group": q["group"],
                "expected_status": "unsupported", "reason_any": q["reason_any"]}
    the_plan = q["plan"]
    out = {"id": q["id"], "question": q["question"], "group": q["group"], "expected_status": "ok",
           "expected": evaluate(the_plan, df), "tolerance": TOLERANCE[the_plan["metric"]]}
    if the_plan.get("limit"):
        out["ordered"] = True
    if q["caveat"]:
        out["caveat_contains"] = q["caveat"]
    out["expected_plan"] = the_plan
    return out


def check_variants(df: pd.DataFrame) -> None:
    """Trap questions only test something if the raw spellings really are in the file."""
    raw = set(df["ship-state"].dropna().str.strip().str.lower())
    for spelling in ["rajsthan", "rj", "orissa", "pondicherry", "new delhi"]:
        print(f"raw spelling {spelling!r} present: {spelling in raw}")


def main() -> None:
    df = load()
    print("rows:", len(df), "| distinct orders:", df["Order ID"].nunique())
    print("lines repeated apart from the index column:",
          df.drop(columns=["index"]).duplicated().sum())
    check_variants(df)
    assert len(QUESTIONS) == 50 and len({q["id"] for q in QUESTIONS}) == 50
    counts = pd.Series([q["group"] for q in QUESTIONS]).value_counts().to_dict()
    assert counts == {"single_metric": 12, "breakdown": 10, "trend": 8, "trap": 10,
                      "unanswerable": 10}, counts

    deduped = load(drop_duplicate_lines=True)
    entries = [entry(q, df) for q in QUESTIONS]
    for q, e in zip(QUESTIONS, entries):
        if "plan" in q and evaluate(q["plan"], deduped) != e["expected"]:
            print(f"NOTE {q['id']}: value changes if the repeated lines are dropped")

    header = ("# Eval questions for the Amazon sample. Generated by eval/answer_key/questions.py\n"
              "# (plain pandas, never imports the app). Frozen after review: fix the code, not this.\n")
    body = yaml.safe_dump({"questions": entries}, sort_keys=False, allow_unicode=True, width=100)
    OUT_PATH.write_text(header + body, encoding="utf-8")
    print(f"wrote {OUT_PATH.relative_to(ROOT)} with {len(entries)} questions")


if __name__ == "__main__":
    main()
