"""Reproduce ChatGPT's baseline numbers with plain pandas, to classify each miss by evidence.

Like eval/answer_key/questions.py, this never imports the app. For each ChatGPT answer it
computes the value under the reading ChatGPT stated (or that its number implies) next to the
answer key's reading, so a miss is explained by data, not by opinion.

    python eval/baseline/reproduce.py
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = ROOT / "data" / "sample" / "amazon_sale_report.csv"

# The answer key's state dictionary entries needed here (eval/answer_key/questions.py).
VARIANTS = {"rj": "Rajasthan", "rajsthan": "Rajasthan", "rajshthan": "Rajasthan",
            "orissa": "Odisha", "new delhi": "Delhi"}


def load() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH, low_memory=False)
    df.columns = df.columns.str.strip()
    df["order_date"] = pd.to_datetime(df["Date"], format="%m-%d-%y")
    df["month"] = df["order_date"].dt.strftime("%Y-%m")
    df["line_cancelled"] = df["Status"] == "Cancelled"
    df["order_cancelled"] = df["Order ID"].map(df.groupby("Order ID")["line_cancelled"].any())
    df["state_raw"] = df["ship-state"].str.strip().str.lower()
    df["state_merged"] = df["state_raw"].map(lambda s: VARIANTS.get(s, s) if isinstance(s, str) else s)
    df["state_merged"] = df["state_merged"].str.lower()
    return df


def rows_rate(rows: pd.DataFrame) -> float:
    """ChatGPT's stated rule: cancelled rows / all rows."""
    return round(100 * rows["line_cancelled"].sum() / len(rows), 2)


def orders_rate(rows: pd.DataFrame) -> float:
    """The answer key's rule: cancelled orders / orders (an order is cancelled if any line is)."""
    ids = rows.drop_duplicates("Order ID")
    return round(100 * ids["order_cancelled"].sum() / len(ids), 4)


def main() -> None:
    df = load()
    kept = df[~df["order_cancelled"]]
    out: list[tuple[str, str, str, str]] = []

    def add(qid: str, chatgpt: str, reproduced: object, key: object, reading: str) -> None:
        out.append((qid, chatgpt, f"{reproduced}", f"{key} | {reading}"))

    add("s01", "78,592,678.30", round(df["Amount"].sum(), 2), round(kept["Amount"].sum(), 2),
        "ChatGPT = sum of Amount over all rows (cancelled included); key excludes cancelled orders")
    add("s03", "652.88", round(df["Amount"].sum() / df["Order ID"].nunique(), 2),
        round(kept["Amount"].sum() / kept["Order ID"].nunique(), 2),
        "ChatGPT = all Amount / all orders; key = revenue / non-cancelled orders")
    amazon = df[df["Fulfilment"] == "Amazon"]
    add("s05", "54,322,151.00", round(amazon["Amount"].sum(), 2),
        round(amazon.loc[~amazon["order_cancelled"], "Amount"].sum(), 2),
        "revenue included cancelled orders")
    kurta = df[df["Category"] == "kurta"]
    add("s07", "14.55", rows_rate(kurta), orders_rate(kurta), "rows rate vs orders rate")
    ka_may = df[(df["state_raw"] == "karnataka") & (df["month"] == "2022-05")]
    add("s08", "3,393,125.07", round(ka_may["Amount"].sum(), 2),
        round(ka_may.loc[~ka_may["order_cancelled"], "Amount"].sum(), 2),
        "revenue included cancelled orders")

    # b03: two ways to count orders per fulfilment type
    by_rows = df["Fulfilment"].value_counts().to_dict()
    per_group = df.groupby("Fulfilment")["Order ID"].nunique().to_dict()
    first_line = df.drop_duplicates("Order ID", keep="first")["Fulfilment"].value_counts().to_dict()
    last_line = df.drop_duplicates("Order ID", keep="last")["Fulfilment"].value_counts().to_dict()
    mixed = int((df.groupby("Order ID")["Fulfilment"].nunique() > 1).sum())
    print("b03 rows per type:", by_rows)
    print("b03 distinct orders within each type (key):", per_group)
    print("b03 each order counted once, type of its first line:", first_line)
    print("b03 each order counted once, type of its last line:", last_line)
    print("b03 orders with lines of both types:", mixed)
    # an order's lines in date order
    by_date = df.sort_values(["Order ID", "order_date"], kind="stable")
    print("b03 orders whose type differs between first and last line:",
          int((by_date.groupby("Order ID")["Fulfilment"].agg(lambda s: s.iloc[0] != s.iloc[-1])).sum()))

    by_state = (df.groupby("state_raw")["Amount"].sum().sort_values(ascending=False).head(5)
                .round(2).to_dict())
    by_state_key = (kept.groupby("state_merged")["Amount"].sum().sort_values(ascending=False)
                    .head(5).round(2).to_dict())
    add("b09", "Maharashtra 13,335,534.14 ...", by_state, by_state_key,
        "revenue included cancelled orders")
    add("b10", "Set 50,284 rows", int((df["Category"] == "Set").sum()),
        int(df.loc[df["Category"] == "Set", "Order ID"].nunique()), "rows vs distinct orders")
    t01 = df[df["month"].isin(["2022-04", "2022-05", "2022-06"])]
    add("t01", "28,838,708.32 / 26,226,476.75 / 23,425,809.38",
        t01.groupby("month")["Amount"].sum().round(2).to_dict(),
        t01[~t01["order_cancelled"]].groupby("month")["Amount"].sum().round(2).to_dict(),
        "revenue included cancelled orders")
    may = df[df["month"] == "2022-05"]
    add("t04", "Amazon 12.52, Merchant 17.07",
        {f: rows_rate(g) for f, g in may.groupby("Fulfilment")},
        {f: orders_rate(g) for f, g in may.groupby("Fulfilment")}, "rows rate vs orders rate")
    rj_raw = df[df["state_raw"] == "rajasthan"]
    rj_all = df[df["state_merged"] == "rajasthan"]
    add("x01", "374 / 2,711 rows = 13.80",
        f"{int(rj_raw['line_cancelled'].sum())} / {len(rj_raw)} rows = {rows_rate(rj_raw)}",
        f"{orders_rate(rj_all)} over {rj_all['Order ID'].nunique()} orders (spellings merged)",
        "rows rate, and RJ / Rajsthan / Rajshthan not merged")
    add("x02", "158 (no warning)", int(df.loc[df["month"] == "2022-03", "Order ID"].nunique()),
        "158 + partial-month caveat", "value right; caveat missing")
    add("x04", "2,506", int(rj_raw["Order ID"].nunique()), int(rj_all["Order ID"].nunique()),
        "RJ / Rajsthan / Rajshthan not merged")
    od_raw = df[df["state_raw"] == "odisha"]
    od_all = df[df["state_merged"] == "odisha"]
    add("x05", "2,021", int(od_raw["Order ID"].nunique()), int(od_all["Order ID"].nunique()),
        "Orissa not merged into Odisha")
    nd_state = df[df["state_raw"] == "new delhi"]
    nd_city = df[df["ship-city"].str.strip().str.lower() == "new delhi"]
    delhi = df[df["state_merged"] == "delhi"]
    add("x07", "76", f"state spelled 'New Delhi': {nd_state['Order ID'].nunique()}; "
        f"city 'New Delhi': {nd_city['Order ID'].nunique()}",
        int(delhi["Order ID"].nunique()), "read 'New Delhi' literally as a state spelling")
    add("x08", "45,858", int(df.loc[df["month"] == "2022-04", "Order ID"].nunique()),
        45858, "matches")

    print()
    for qid, chatgpt, reproduced, key in out:
        print(f"{qid}\n  ChatGPT:    {chatgpt}\n  reproduced: {reproduced}\n  key:        {key}")


if __name__ == "__main__":
    main()
