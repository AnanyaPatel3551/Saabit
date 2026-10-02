"""Write shopify_synthetic.csv: a small, made-up Shopify-style order export.

It exists to show that Saabit works on a differently shaped file: other headers, day-first
dates (DD/MM/YYYY), a "Financial Status" column and "Shipping Province" for the state. Every
row is generated here from a fixed random seed, so the file is the same on every run. It is
not real data.

    python data/sample_shopify/make_synthetic.py
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).with_name("shopify_synthetic.csv")
SEED = 20240101
ORDERS = 1500
START, DAYS = date(2024, 1, 1), 91  # 1 Jan to 31 Mar 2024

PLACES = [("Maharashtra", ["Mumbai", "Pune", "Nagpur"]), ("Karnataka", ["Bengaluru", "Mysuru"]),
          ("Delhi", ["New Delhi"]), ("Tamil Nadu", ["Chennai", "Coimbatore"]),
          ("Telangana", ["Hyderabad"]), ("Gujarat", ["Ahmedabad", "Surat"]),
          ("Rajasthan", ["Jaipur", "Udaipur"]), ("West Bengal", ["Kolkata"]),
          ("Uttar Pradesh", ["Lucknow", "Noida"]), ("Kerala", ["Kochi"])]
PLACE_WEIGHTS = [18, 14, 12, 10, 9, 8, 8, 7, 9, 5]
PRODUCTS = [("Kurta", "KUR", 899), ("Saree", "SAR", 1899), ("Dupatta", "DUP", 449),
            ("Top", "TOP", 599), ("Palazzo", "PAL", 699)]
STATUSES = ["paid", "pending", "refunded", "Cancelled"]
STATUS_WEIGHTS = [78, 6, 5, 11]
SOURCES = ["web", "Instagram", "WhatsApp"]
HEADERS = ["Order Number", "Created at", "Total", "Financial Status", "Shipping Province",
           "Shipping City", "Lineitem quantity", "Lineitem sku", "Product Type", "Source"]


def rows(rng: random.Random) -> list[list[str]]:
    out = []
    for number in range(1001, 1001 + ORDERS):
        day = START + timedelta(days=rng.randrange(DAYS))
        state, cities = rng.choices(PLACES, PLACE_WEIGHTS)[0]
        city = rng.choice(cities)
        status = rng.choices(STATUSES, STATUS_WEIGHTS)[0]
        source = rng.choice(SOURCES)
        # 1 to 3 different products per order, so no two lines of an order are identical
        items = rng.sample(PRODUCTS, rng.choices([1, 2, 3], [70, 22, 8])[0])
        for product, code, price in items:
            qty = rng.choices([1, 2, 3], [80, 15, 5])[0]
            size = rng.choice(["S", "M", "L", "XL"])
            out.append([f"#{number}", day.strftime("%d/%m/%Y"), f"{price * qty:.2f}", status,
                        state, city, str(qty), f"{code}-{size}", product, source])
    return out


def main() -> None:
    rng = random.Random(SEED)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(HEADERS)
        writer.writerows(rows(rng))
    print(f"wrote {OUT.name}")


if __name__ == "__main__":
    main()
