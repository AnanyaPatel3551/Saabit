"""Report which questions an uploaded file can answer."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityItem:
    topic: str
    reason: str


@dataclass(frozen=True)
class CapabilityReport:
    """What the confirmed roles allow (FR-3.5)."""

    can_answer: list[CapabilityItem]
    cannot_answer: list[CapabilityItem]


# topic, roles it needs, what to say when a role is missing
REQUIREMENTS: list[tuple[str, tuple[str, ...], str]] = [
    ("revenue", ("amount", "order_date"), "needs amount and date columns"),
    ("orders", ("order_id",), "needs an order ID column"),
    ("average order value", ("amount", "order_id"), "needs amount and order ID columns"),
    ("units sold", ("qty",), "no quantity column was confirmed"),
    ("cancellation rate", ("status",), "no order status column was confirmed"),
    ("trend by month", ("order_date",), "needs a date column"),
    ("breakdown by state", ("state",), "no state column was confirmed"),
    ("breakdown by city", ("city",), "no city column was confirmed"),
    ("breakdown by category", ("category",), "no category column was confirmed"),
    ("breakdown by product (SKU)", ("sku",), "no product (SKU) column was confirmed"),
    ("breakdown by fulfilment", ("fulfilment",), "no fulfilment column was confirmed"),
    ("breakdown by sales channel", ("channel",), "no sales channel column was confirmed"),
]

ALWAYS_UNSUPPORTED = [
    CapabilityItem("profit and margin",
                   "the file has no cost column, so profit cannot be computed"),
    CapabilityItem("COD and payment mix", "the file has no payment method column"),
    CapabilityItem("forecasts", "Saabit does not forecast: a few months of data cannot support "
                                "an honest forecast"),
]


def capability_report(roles: set[str]) -> CapabilityReport:
    """Split the question types into can and cannot answer, each with a reason."""
    can, cannot = [], []
    for topic, needed, missing_reason in REQUIREMENTS:
        if all(role in roles for role in needed):
            columns = " and ".join(needed).replace("_", " ")
            noun = "column" if len(needed) == 1 else "columns"
            can.append(CapabilityItem(topic, f"uses the confirmed {columns} {noun}"))
        else:
            cannot.append(CapabilityItem(topic, missing_reason))
    return CapabilityReport(can_answer=can, cannot_answer=cannot + ALWAYS_UNSUPPORTED)
