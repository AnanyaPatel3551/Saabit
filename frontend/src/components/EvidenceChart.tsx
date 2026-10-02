import { useState } from "react";
import type { Comparison, Plan, ResultRow } from "../api/types";
import { formatValue, indianDigits, keyLabel } from "../lib/format";
import { humanize } from "../lib/plan";

const MAX_BARS = 12;
const TIME = new Set(["month", "week"]);
/** Metrics defined over orders that are not cancelled count only those orders too
 * (backend metrics.Metric.orders_counted). */
const LIVE_ORDER_METRICS = new Set(["revenue", "aov", "units"]);

export function ordersLabel(metric: string | null): string {
  return metric && LIVE_ORDER_METRICS.has(metric) ? "non-cancelled orders" : "orders";
}

interface Bar {
  key: string;
  label: string;
  value: number;
  shown: string;
  partial: boolean;
}

function bars(plan: Plan, rows: ResultRow[], partialMonths: string[]): Bar[] {
  return rows.map((row) => {
    const key = plan.group_by.map((d) => String(row[d] ?? "")).join("|");
    const month = plan.group_by[0] === "month" ? String(row.month ?? "") : "";
    return {
      key,
      label: plan.group_by.map((d) => keyLabel(d, row[d])).join(" · ") || "All",
      value: Math.max(row.value ?? 0, 0),
      shown: formatValue(plan.metric, row.value),
      partial: partialMonths.includes(month),
    };
  });
}

/** What the filters selected, for the comparison bar: "Rajasthan", "Amazon, Set". */
function filterLabel(plan: Plan): string {
  return plan.filters.map((f) => (f.op === "not_in" ? "not " : "") + f.values.join(", ")).join(", ")
    || "This selection";
}

/**
 * The answer's chart: horizontal bars for groups (largest first, values labelled), columns
 * for months and weeks (a partial month lighter and marked), and for a filtered single number
 * a thin bar against all orders. Nothing is drawn when there is nothing to compare, so the
 * card never shows an empty chart area.
 */
export function EvidenceChart({ plan, rows, comparison, partialMonths = [], compact }: {
  plan: Plan;
  rows: ResultRow[];
  comparison?: Comparison | null;
  partialMonths?: string[];
  compact?: boolean;
}) {
  const [asTable, setAsTable] = useState(false);
  const metric = plan.metric;

  if (plan.group_by.length === 0) {
    const value = rows[0]?.value ?? null;
    if (!comparison || comparison.value === null || value === null) return null;
    const max = Math.max(value, comparison.value, 1e-9);
    const items = [
      { label: filterLabel(plan), value, emphasis: true },
      { label: comparison.label, value: comparison.value, emphasis: false },
    ];
    return (
      <figure className="flex flex-col gap-1.5" data-testid="evidence-chart"
        aria-label={`${filterLabel(plan)} ${formatValue(metric, value)} compared with ${comparison.label} ${formatValue(metric, comparison.value)}`}>
        {items.map((item) => (
          <div key={item.label} className="grid grid-cols-[minmax(0,7rem)_1fr_auto] items-center gap-2 text-xs">
            <span className="truncate text-muted">{item.label}</span>
            <span className="h-2 rounded-full bg-raised">
              <span className={`block h-2 rounded-full ${item.emphasis ? "bg-gold" : "bg-muted/60"}`}
                style={{ width: `${(item.value / max) * 100}%` }} />
            </span>
            <span className="tabular-nums text-text">{formatValue(metric, item.value)}</span>
          </div>
        ))}
      </figure>
    );
  }

  if (rows.length === 0) return null;
  const all = bars(plan, rows, partialMonths);
  const overTime = plan.group_by.length === 1 && TIME.has(plan.group_by[0]);
  const shown = overTime ? all : [...all].sort((a, b) => b.value - a.value).slice(0, MAX_BARS);
  const max = Math.max(...shown.map((b) => b.value), 1e-9);
  const hidden = all.length - shown.length;

  return (
    <div className="flex flex-col gap-2">
      {asTable ? (
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-xs">
            <caption className="sr-only">{humanize(metric ?? "value")} by {plan.group_by.join(" and ")}</caption>
            <thead className="text-left text-muted">
              <tr>
                <th scope="col" className="py-1 pr-3 font-normal">{plan.group_by.map(humanize).join(" · ")}</th>
                <th scope="col" className="py-1 pr-3 text-right font-normal">{humanize(metric ?? "value")}</th>
                <th scope="col" className="py-1 text-right font-normal">
                  {ordersLabel(metric).replace(/^./, (c) => c.toUpperCase())}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={all[i].key} className="border-t border-line">
                  <td className="py-1 pr-3">{all[i].label}{all[i].partial ? " (partial)" : ""}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">{all[i].shown}</td>
                  <td className="py-1 text-right tabular-nums">{indianDigits(row.orders)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : overTime ? (
        <figure data-testid="evidence-chart" aria-label={`${humanize(metric ?? "value")} by ${plan.group_by[0]}`}
          className="overflow-x-auto">
          <div className={`flex items-end gap-1.5 ${compact ? "h-28" : "h-40"}`} style={{ minWidth: `${shown.length * 2.5}rem` }}>
            {shown.map((bar) => (
              <div key={bar.key} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1">
                <span className="text-[10px] tabular-nums text-text">{bar.shown}</span>
                <span className={`w-full rounded-t ${bar.partial ? "bg-gold/35" : "bg-gold"}`}
                  style={{ height: `${Math.max((bar.value / max) * 100, 1)}%` }} />
                <span className="text-[10px] text-muted">{bar.label}</span>
                {bar.partial && <span className="text-[10px] text-amber">partial</span>}
              </div>
            ))}
          </div>
        </figure>
      ) : (
        <figure data-testid="evidence-chart" aria-label={`${humanize(metric ?? "value")} by ${plan.group_by.join(" and ")}, largest first`}
          className="flex flex-col gap-1.5">
          {shown.map((bar) => (
            <div key={bar.key} className="grid grid-cols-[minmax(0,8rem)_1fr_auto] items-center gap-2 text-xs">
              <span className="truncate text-muted" title={bar.label}>{bar.label}</span>
              <span className="h-2 rounded-full bg-raised">
                <span className="block h-2 rounded-full bg-gold" style={{ width: `${(bar.value / max) * 100}%` }} />
              </span>
              <span className="tabular-nums text-text">{bar.shown}</span>
            </div>
          ))}
          {hidden > 0 && <p className="text-xs text-muted">and {hidden} more (see the table)</p>}
        </figure>
      )}
      <button type="button" onClick={() => setAsTable(!asTable)} aria-pressed={asTable}
        className="min-h-9 self-start text-xs text-muted hover:text-text">
        {asTable ? "View as chart" : "View as table"}
      </button>
    </div>
  );
}
