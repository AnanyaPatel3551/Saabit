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
