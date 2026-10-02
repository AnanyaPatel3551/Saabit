import { useState } from "react";
import type { Dimension, FilterColumn, MetricName, Plan } from "../api/types";
import { DIMENSIONS, FILTER_COLUMNS, METRIC_NAMES, humanize } from "../lib/plan";

const chip = "min-h-9 rounded-full border border-line bg-raised px-3 py-1 text-sm text-text";
const select = `${chip} cursor-pointer appearance-none pr-6`;

/** The file's first and last order date (YYYY-MM-DD), when known. */
export interface DataRange {
  min: string | null;
  max: string | null;
}

/**
 * "Understood as" chips: metric, group by, filters and dates. Every edit hands a new plan
 * to onChange, which runs it with /run directly (no LLM, so chips work when it is down).
 * With no date range, the date fields show the data's real range; changing one sets a range
 * whose other end stays at the data's bound.
 */
export function PlanChips({ plan, onChange, disabled, range, preview }: {
  plan: Plan;
  onChange: (plan: Plan) => void;
  disabled?: boolean;
  range?: DataRange;
  /** Shown for illustration only (the landing page): nothing can be edited. */
  preview?: boolean;
}) {
  const [adding, setAdding] = useState(false);
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
    setAdding(false);
  };

  const start = plan.date_range?.start ?? range?.min ?? "";
  const end = plan.date_range?.end ?? range?.max ?? "";
  const setDate = (side: "start" | "end", value: string) => {
    if (!value) return update({ date_range: null });
    const next = { start, end, [side]: value };
    if (!next.start || !next.end) return;
    update({ date_range: next });
  };

  return (
    <fieldset disabled={disabled || preview} className={`flex flex-wrap items-center gap-2 ${
      preview ? "" : "disabled:opacity-60"}`}>
      <legend className="mb-2 text-xs uppercase tracking-wider text-muted">Understood as</legend>

      <label className="sr-only" htmlFor="chip-metric">Metric</label>
      <select id="chip-metric" className={select} value={plan.metric ?? ""}
        onChange={(e) => update({ metric: e.target.value as MetricName })}>
        {METRIC_NAMES.map((m) => <option key={m} value={m}>{humanize(m)}</option>)}
      </select>

      {[...plan.group_by, ...(plan.group_by.length < 2 && !preview ? [""] : [])].map((dim, index) => (
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
          {!preview && (
            <button type="button" aria-label={`Remove filter ${humanize(filter.column)}`}
              className="text-muted hover:text-bad"
              onClick={() => update({ filters: plan.filters.filter((_, i) => i !== index) })}>
              ×
            </button>
          )}
        </span>
      ))}

      {!preview && !adding && (
        <button type="button" className={`${chip} text-gold`} onClick={() => setAdding(true)}>
          + filter
        </button>
      )}
      {!preview && adding && (
        <span className="inline-flex flex-wrap items-center gap-1">
          <label className="sr-only" htmlFor="chip-filter-column">Filter column</label>
          <select id="chip-filter-column" className={select} value={filterColumn}
            onChange={(e) => setFilterColumn(e.target.value as FilterColumn)}>
            {FILTER_COLUMNS.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
          </select>
          <label className="sr-only" htmlFor="chip-filter-value">Filter value</label>
          <input id="chip-filter-value" className={`${chip} w-32`} placeholder="e.g. Rajasthan"
            autoFocus value={filterValue} onChange={(e) => setFilterValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); addFilter(); }
              if (e.key === "Escape") setAdding(false);
            }} />
          <button type="button" className={`${chip} text-gold`} onClick={addFilter}>Add</button>
          <button type="button" className="min-h-9 px-2 text-xs text-muted hover:text-text"
            onClick={() => setAdding(false)}>
            Cancel
          </button>
        </span>
      )}

      {(start || end) && (
        <span className="inline-flex flex-wrap items-center gap-1 text-xs text-muted">
          <label htmlFor="chip-start">from</label>
          <input id="chip-start" type="date" className={chip} value={start}
            min={range?.min ?? undefined} max={range?.max ?? undefined}
            onChange={(e) => setDate("start", e.target.value)} />
          <label htmlFor="chip-end">to</label>
          <input id="chip-end" type="date" className={chip} value={end}
            min={range?.min ?? undefined} max={range?.max ?? undefined}
            onChange={(e) => setDate("end", e.target.value)} />
          {!plan.date_range && <span className="text-muted">(all dates)</span>}
        </span>
      )}
    </fieldset>
  );
}
