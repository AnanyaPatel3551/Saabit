// Types mirroring the backend Pydantic models in backend/app/api/schemas.py and
// backend/app/core/plan.py. Keep them in step when the API changes.

export type Role =
  | "order_id" | "order_date" | "amount" | "status" | "state" | "city"
  | "category" | "sku" | "fulfilment" | "qty" | "channel";

export type MetricName = "revenue" | "orders" | "units" | "aov" | "cancelled_orders"
  | "cancellation_rate";

export type Dimension = "month" | "week" | "state" | "city" | "category" | "sku"
  | "fulfilment" | "channel";

export type FilterColumn = "state" | "city" | "category" | "sku" | "fulfilment" | "channel";

export interface RoleOut {
  role: Role;
  column: string | null;
  confidence: number;
  reasons: string[];
  samples: string[];
}

export interface CapabilityItem {
  topic: string;
  reason: string;
}

export interface DataCheck {
  dataset_id: string;
  rows_in: number;
  rows_out: number;
  partial_months: string[];
  unknown_states: string[];
  fixes: { rule: string; rows_affected: number; entries: number }[];
  capability: { can_answer: CapabilityItem[]; cannot_answer: CapabilityItem[] };
  date_min?: string | null;  // first order date, YYYY-MM-DD
  date_max?: string | null;
  orders?: number | null;  // distinct order IDs
}

export interface Dataset {
  dataset_id: string;
  filename: string;
  size_bytes: number;
  rows: number;
  created_at: string;
  columns: string[];
  roles: RoleOut[];
  roles_confirmed: boolean;
  missing_required: string[];
  unmapped_columns: string[];
  data_check: DataCheck | null;
}

export interface Filter {
  column: FilterColumn;
  op: "eq" | "in" | "not_in";
  values: string[];
}

export interface Plan {
  status: "ok" | "needs_clarification" | "unsupported";
  metric: MetricName | null;
  group_by: Dimension[];
  filters: Filter[];
  date_range: { start: string; end: string } | null;
  sort: { by: "value" | "key"; dir: "asc" | "desc" } | null;
  limit: number | null;
  clarification: { question: string; options: string[] } | null;
  unsupported_reason: string | null;
}

export interface PlanOut {
  plan: Plan;
  caveats: string[];
  cached: boolean;
}

/** One result row: group keys (by dimension name), value and the orders behind it. */
export type ResultRow = { value: number | null; orders: number } & Record<string, unknown>;

export interface Card {
  card_id: string;
  dataset_id: string;
  plan: Plan;
  sql: string;
  pandas_code: string;
  verified: boolean;
  result: ResultRow[];
  caveats: string[];
  row_count: number;
  sql_result: ResultRow[] | null;
  pandas_result: ResultRow[] | null;
  mismatches: string[];
  created_at: string;
  /** Attached in the browser from RunOut, so the evidence drawer can draw the same chart. */
  comparison?: Comparison | null;
}

/** The same measure over all orders, shown next to a filtered single number. */
export interface Comparison {
  label: string;
  value: number | null;
  verified: boolean;
  card_id: string;
}

/** /run answers as soon as both engines finish; sentence is the template until the LLM's arrives. */
export interface RunOut {
  verified: boolean;
  sentence: string | null;
  source: "template" | "unverified";
  sentence_status: "pending" | "final";
  note: string | null;
  card: Card;
  comparison?: Comparison | null;
  /** Served from the answer cache: nothing was recomputed (the UI looks the same). */
  cached?: boolean;
  /** "How this was calculated", written by code from the metric catalogue and the plan. */
  explanation?: string[];
  /** The first source rows behind the card. */
  rows_preview?: Record<string, unknown>[];
}

export interface SentenceOut {
  sentence: string | null;
  source: "llm" | "template" | "unverified";
  note: string | null;
}

export interface RowsOut {
  card_id: string;
  page: number;
  page_size: number;
  total_rows: number;
  pages: number;
  rows: Record<string, unknown>[];
}

export interface Insight {
  code: string;
  title: string;
  status: "ok" | "unverified" | "skipped";
  reason: string | null;
  card_ids: string[];
  verified: boolean;
  /** "engines": SQL and pandas computed it; "fix_log": a summary of cleaning, never Verified. */
  source?: "engines" | "fix_log" | null;
  caveats?: string[];
  text: string | null;
}

export interface Recommendation {
  code: string;
  title: string;
  status: "fired" | "not_fired" | "skipped";
  reason: string | null;
  cites: string[];
  text: string | null;
  confidence: "High" | "Medium" | "Low" | null;
  confidence_reason?: string;
  impact: { value: number; formula: string; assumption: string; caveat: string } | null;
}

export interface Overview {
  status: "computing" | "ready" | "failed";
  reason: string | null;
  computed_at: string | null;
  months: { training: string[]; test: string | null } | null;
  data_check: DataCheck;
  insights: Insight[];
  recommendations: Recommendation[];
  rules: Recommendation[];
}

export interface Health {
  status: string;
  version: string;
  llm: {
    provider: string;
    model: string;
    status: "ok" | "unavailable" | "not_configured" | "unknown";
    reason: string | null;
    checked_at: string | null;
    providers?: { name: string; model: string; configured: boolean; cooling_until: string | null }[];
    /** Last call: "ok" (first provider), "fallback", "down"; "unknown" before any call. */
    state?: "ok" | "fallback" | "down" | "unknown";
  };
}

export interface Score {
  correct: number;
  total: number;
}

/** /api/eval-summary: each part is null until its tool has been run. */
export interface EvalSummary {
  eval: {
    answerable: Score;
    refused: Score;
    verified_but_wrong: number;
    anchors_answerable: Score;
    anchors_refused: Score;
    served_by: string[];
    finished_at: string;
    used_saved_plans: boolean;
  } | null;
  baseline: { answerable: Score; refused: Score; product: string | null } | null;
  tests: { passed: number; skipped: number; date: string } | null;
}
