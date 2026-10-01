import { useState } from "react";
import type { Dimension, FilterColumn, MetricName, Plan } from "../api/types";
import { DIMENSIONS, FILTER_COLUMNS, METRIC_NAMES, humanize } from "../lib/plan";

const chip = "rounded-full border border-line bg-raised px-3 py-1 text-sm text-text";
const select = `${chip} cursor-pointer appearance-none pr-6`;

/**
 * "Understood as" chips: metric, group by, filters and dates. Every edit hands a new plan
 * to onChange, which runs it with /run directly (no LLM, so chips work when it is down).
 */
export function PlanChips({ plan, onChange, disabled }: {
  plan: Plan;
  onChange: (plan: Plan) => void;
  disabled?: boolean;
}) {
  const [filterColumn, setFilterColumn] = useState<FilterColumn>("state");
  const [filterValue, setFilterValue] = useState("");

  const update = (patch: Partial<Plan>) => onChange({ ...plan, ...patch });

  const setGroup = (index: number, value: string) => {
    const next = [...plan.group_by];
    if (value === "") next.splice(index, 1);
    else next[index] = value as Dimension;
    const groupBy = [...new Set(next)];
    const timeSort = groupBy[0] === "month" || groupBy[0] === "week";
    update({ group_by: groupBy, sort: timeSort ? { by: "key", dir: "asc" } : plan.sort });
  };

  const addFilter = () => {
    const value = filterValue.trim();
    if (!value) return;
    update({ filters: [...plan.filters, { column: filterColumn, op: "eq", values: [value] }] });
    setFilterValue("");
  };

  const setDate = (side: "start" | "end", value: string) => {
    if (!value) return update({ date_range: null });
    const current = plan.date_range ?? { start: value, end: value };
    update({ date_range: { ...current, [side]: value } });
  };

  return (
    <fieldset disabled={disabled} className="flex flex-wrap items-center gap-2 disabled:opacity-60">
      <legend className="mb-2 text-xs uppercase tracking-wider text-muted">Understood as</legend>

      <label className="sr-only" htmlFor="chip-metric">Metric</label>
      <select id="chip-metric" className={select} value={plan.metric ?? ""}
        onChange={(e) => update({ metric: e.target.value as MetricName })}>
        {METRIC_NAMES.map((m) => <option key={m} value={m}>{humanize(m)}</option>)}
      </select>

      {[...plan.group_by, ...(plan.group_by.length < 2 ? [""] : [])].map((dim, index) => (
        <span key={`${index}-${dim}`} className="inline-flex items-center gap-1">
          <span className="text-xs text-muted">{index === 0 ? "by" : "and"}</span>
          <label className="sr-only" htmlFor={`chip-group-${index}`}>Group by {index + 1}</label>
          <select id={`chip-group-${index}`} className={select} value={dim}
            onChange={(e) => setGroup(index, e.target.value)}>
            <option value="">{dim ? "(remove)" : "+ group"}</option>
            {DIMENSIONS.map((d) => <option key={d} value={d}>{humanize(d)}</option>)}
          </select>
        </span>
      ))}

      {plan.filters.map((filter, index) => (
        <span key={`${filter.column}-${index}`} className={`${chip} inline-flex items-center gap-2`}>
          {humanize(filter.column)} {filter.op === "not_in" ? "is not" : "is"} {filter.values.join(", ")}
          <button type="button" aria-label={`Remove filter ${humanize(filter.column)}`}
            className="text-muted hover:text-bad"
            onClick={() => update({ filters: plan.filters.filter((_, i) => i !== index) })}>
            ×
          </button>
        </span>
      ))}

      <span className="inline-flex items-center gap-1">
        <label className="sr-only" htmlFor="chip-filter-column">Filter column</label>
        <select id="chip-filter-column" className={select} value={filterColumn}
          onChange={(e) => setFilterColumn(e.target.value as FilterColumn)}>
          {FILTER_COLUMNS.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
        </select>
        <label className="sr-only" htmlFor="chip-filter-value">Filter value</label>
        <input id="chip-filter-value" className={`${chip} w-28`} placeholder="value"
          value={filterValue} onChange={(e) => setFilterValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addFilter(); } }} />
        <button type="button" className={`${chip} text-gold`} onClick={addFilter}>+ filter</button>
      </span>

      <span className="inline-flex items-center gap-1 text-xs text-muted">
        <label htmlFor="chip-start">from</label>
        <input id="chip-start" type="date" className={chip} value={plan.date_range?.start ?? ""}
          onChange={(e) => setDate("start", e.target.value)} />
        <label htmlFor="chip-end">to</label>
        <input id="chip-end" type="date" className={chip} value={plan.date_range?.end ?? ""}
          onChange={(e) => setDate("end", e.target.value)} />
      </span>
    </fieldset>
  );
}
