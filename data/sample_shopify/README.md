# Synthetic Shopify-style sample

`shopify_synthetic.csv` is **synthetic**: every row is made up by `make_synthetic.py` from a
fixed random seed. It is not real sales data and describes no real shop.

It exists to show that Saabit works on a differently shaped file than the Amazon sample:

- Shopify-style headers: `Order Number`, `Created at`, `Total`, `Financial Status`,
  `Shipping Province`, `Shipping City`, `Lineitem quantity`, `Lineitem sku`, `Product Type`,
  `Source`;
- day-first dates (DD/MM/YYYY), 1 Jan to 31 Mar 2024;
- 1,500 orders in 2,073 lines across 10 states (no two lines of an order are identical).

`Financial Status` includes some `Cancelled` values so the cancellation rate has something to
measure (real Shopify exports use a separate cancelled flag).

Regenerate (the output is identical every time):

```powershell
backend\.venv\Scripts\python.exe data\sample_shopify\make_synthetic.py
```
