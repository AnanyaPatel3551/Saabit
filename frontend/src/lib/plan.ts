// Names the plan chips can choose from. These mirror the Plan schema's allowed values
// only; which metrics a file supports, and what they mean, stay in backend
// core/metrics.py. If a chip picks something the file cannot answer, /run says why.

import type { Dimension, FilterColumn, MetricName, Plan, Role } from "../api/types";

export const ROLES: Role[] = ["order_id", "order_date", "amount", "status", "state", "city",
  "category", "sku", "fulfilment", "qty", "channel"];
export const REQUIRED_ROLES: Role[] = ["order_id", "order_date", "amount"];

export const METRIC_NAMES: MetricName[] = ["revenue", "orders", "units", "aov",
  "cancelled_orders", "cancellation_rate"];

export const DIMENSIONS: Dimension[] = ["month", "week", "state", "city", "category", "sku",
  "fulfilment", "channel"];

export const FILTER_COLUMNS: FilterColumn[] = ["state", "city", "category", "sku",
  "fulfilment", "channel"];

/** What each column type is called on the confirm screen. */
export const ROLE_NAMES: Record<Role, string> = {
  order_id: "Order ID", order_date: "Order date", amount: "Amount (₹)", status: "Status",
  state: "State", city: "City", category: "Product category", sku: "Product (SKU)",
  fulfilment: "Who ships it (fulfilment)", qty: "Quantity", channel: "Sales channel",
};

/** "cancellation_rate" -> "Cancellation rate"; "aov" -> "AOV". */
export function humanize(name: string): string {
  if (name === "aov") return "AOV";
  if (name === "sku") return "SKU";
  const text = name.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The planner ends refusals with "Nearest question: ...". */
export function suggestedQuestion(reason: string | null | undefined): string | null {
  const match = reason?.match(/Nearest question:\s*(.+?)\.?\s*$/i);
  return match ? match[1].trim() : null;
}

export function reasonWithoutSuggestion(reason: string | null | undefined): string {
  return (reason ?? "").replace(/\s*Nearest question:.*$/i, "").trim();
}

export function okPlan(patch: Partial<Plan>): Plan {
  return {
    status: "ok", metric: null, group_by: [], filters: [], date_range: null, sort: null,
    limit: null, clarification: null, unsupported_reason: null, ...patch,
  };
}

/** Example chips carry ready plans, so they run with /run even when the LLM is down. */
export const EXAMPLES: { question: string; plan: Plan }[] = [
  { question: "Top 5 states by revenue",
    plan: okPlan({ metric: "revenue", group_by: ["state"], sort: { by: "value", dir: "desc" }, limit: 5 }) },
  { question: "Monthly revenue trend",
    plan: okPlan({ metric: "revenue", group_by: ["month"], sort: { by: "key", dir: "asc" } }) },
  { question: "Cancellation rate by fulfilment",
    plan: okPlan({ metric: "cancellation_rate", group_by: ["fulfilment"] }) },
  { question: "Top categories by revenue",
    plan: okPlan({ metric: "revenue", group_by: ["category"], sort: { by: "value", dir: "desc" }, limit: 10 }) },
];

/** Plain names for sellers. Technical names stay in "Technical details". */
const METRIC_WORDS: Record<MetricName, string> = {
  revenue: "Revenue", orders: "Orders", units: "Units sold", aov: "Average order value",
  cancelled_orders: "Cancelled orders", cancellation_rate: "Cancellation rate",
};
const DIMENSION_WORDS: Record<Dimension, string> = {
  month: "month", week: "week", state: "state", city: "city", category: "category",
  sku: "product code", fulfilment: "fulfilment", channel: "sales channel",
};
/** Metrics that leave cancelled orders out (backend metrics.Metric.orders_counted). */
const WITHOUT_CANCELLED = new Set<MetricName>(["revenue", "aov", "units"]);

export function metricWords(metric: MetricName | null): string {
  return metric ? METRIC_WORDS[metric] : "Answer";
}

export function dimensionWords(dimension: Dimension | string): string {
  return DIMENSION_WORDS[dimension as Dimension] ?? dimension;
}

function dayText(day: string): string {
  const [y, m, d] = day.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB",
    { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

/** "Revenue · by month · all dates · excluding cancelled orders": what an answer counted. */
export function describePlan(plan: Plan): string {
  const parts = [metricWords(plan.metric)];
  if (plan.group_by.length) parts.push(`by ${plan.group_by.map(dimensionWords).join(" and ")}`);
  for (const f of plan.filters) {
    parts.push(`${f.op === "not_in" ? "not " : ""}${f.values.join(", ")}`);
  }
  parts.push(plan.date_range
    ? `${dayText(plan.date_range.start)} – ${dayText(plan.date_range.end)}` : "all dates");
  if (plan.metric && WITHOUT_CANCELLED.has(plan.metric)) parts.push("excluding cancelled orders");
  if (plan.limit) parts.push(`top ${plan.limit}`);
  return parts.join(" · ");
}
