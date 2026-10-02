"""Metric definitions: the single source of truth for every metric.

This module is the spec that both engines (compile_sql and compile_pandas) implement
independently. It holds data only: names, labels, units, required roles, definitions and
rounding. There is no computation here, so a bug cannot be shared by both engines through it.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    unit: str  # "INR", "orders", "units" or "percent"
    required_roles: tuple[str, ...]
    definition: str
    decimals: int  # rounding for display; comparisons use full precision
    # Which orders the result's "orders" column counts, matching the definition: metrics
    # over orders that are not cancelled count only those; the others count every order.
    orders_counted: str = "all"  # "all" or "not_cancelled"


METRICS: dict[str, Metric] = {
    "revenue": Metric(
        name="revenue",
        label="Revenue",
        unit="INR",
        required_roles=("order_id", "order_date", "amount"),
        definition="Sum of amount over order lines whose order is not cancelled.",
        decimals=2,
        orders_counted="not_cancelled",
    ),
    "orders": Metric(
        name="orders",
        label="Orders",
        unit="orders",
        required_roles=("order_id", "order_date"),
        definition="Count of distinct order IDs, cancelled or not.",
        decimals=0,
    ),
    "units": Metric(
        name="units",
        label="Units sold",
        unit="units",
        required_roles=("order_id", "order_date", "qty"),
        definition="Sum of qty over order lines whose order is not cancelled.",
        decimals=0,
        orders_counted="not_cancelled",
    ),
    "aov": Metric(
        name="aov",
        label="Average order value",
        unit="INR",
        required_roles=("order_id", "order_date", "amount"),
        definition="Revenue divided by the count of distinct orders that are not cancelled.",
        decimals=2,
        orders_counted="not_cancelled",
    ),
    "cancelled_orders": Metric(
        name="cancelled_orders",
        label="Cancelled orders",
        unit="orders",
        required_roles=("order_id", "order_date", "status"),
        definition="Count of distinct orders that are cancelled.",
        decimals=0,
    ),
    "cancellation_rate": Metric(
        name="cancellation_rate",
        label="Cancellation rate",
        unit="percent",
        required_roles=("order_id", "order_date", "status"),
        definition="Distinct cancelled orders divided by distinct orders, times 100.",
        decimals=1,
    ),
}


@dataclass(frozen=True)
class Dimension:
    name: str
    column: str  # canonical column in clean.parquet
    role: str
    key_format: str  # how the group key is written in results
    filterable: bool


DIMENSIONS: dict[str, Dimension] = {
    "month": Dimension("month", "order_date", "order_date", "YYYY-MM of the order date", False),
    "week": Dimension("week", "order_date", "order_date",
                      "YYYY-MM-DD of the Monday starting the week", False),
    "state": Dimension("state", "state", "state", "canonical state name", True),
    "city": Dimension("city", "city", "city", "city as written", True),
    "category": Dimension("category", "category", "category", "category as written", True),
    "sku": Dimension("sku", "sku", "sku", "SKU as written", True),
    "fulfilment": Dimension("fulfilment", "fulfilment", "fulfilment", "fulfilment as written",
                            True),
    "channel": Dimension("channel", "channel", "channel", "sales channel as written", True),
}

MAX_ROWS = 500
MAX_GROUP_BY = 2
SORT_DECIMALS = 6  # values are rounded to this before sorting, so float noise cannot reorder ties
SMALL_GROUP_ORDERS = 30  # FR-6.3: groups with fewer orders get a small-sample caveat
REL_TOLERANCE = 1e-6  # FR-6.1
ABS_TOLERANCE = 0.01  # FR-6.1

# Rules both engines follow where the definitions above leave a choice. Each engine
# implements these on its own; nothing here is executable.
SHARED_RULES = (
    "Filters and the date range select order lines first; the metric is computed on those lines.",
    "The date range is inclusive at both ends and compares the order date.",
    "An order counts in every group it has at least one line in.",
    "Lines with a blank value in a grouping column are left out of grouped results.",
    "eq and in keep lines whose value is listed; not_in keeps lines whose value is present "
    "and not listed (blank values are dropped).",
    "A cancelled order is one whose is_cancelled flag is true; if the file has no status "
    "column, no order is treated as cancelled and a caveat says so.",
    "Sums over no lines are 0; a ratio with a zero denominator is blank.",
    "Without a sort, rows are ordered by the group keys ascending. With sort by value, rows "
    "are ordered by value rounded to SORT_DECIMALS in the given direction, then by the group "
    "keys ascending; blank values sort last. With sort by key, the keys use the given "
    "direction. At most MAX_ROWS rows (or the plan's limit, if smaller).",
    "Every result row also carries orders: the distinct orders behind that row.",
)
