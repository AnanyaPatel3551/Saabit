import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { Plan, ResultRow } from "../api/types";
import { formatValue, indianDigits, keyLabel } from "../lib/format";
import { humanize } from "../lib/plan";

interface ChartRow {
  label: string;
  value: number | null;
  orders: number;
}

/** Group keys joined into one label, e.g. "Set · Merchant". */
export function chartRows(plan: Plan, rows: ResultRow[]): ChartRow[] {
  return rows.map((row) => ({
    label: plan.group_by.map((d) => keyLabel(d, row[d])).join(" · ") || "All",
    value: row.value,
    orders: row.orders,
  }));
}

/** Bar for groups, line for months and weeks, with a "view as table" toggle. */
export function ResultChart({ plan, rows }: { plan: Plan; rows: ResultRow[] }) {
  const [asTable, setAsTable] = useState(false);
  const data = chartRows(plan, rows);
  const metric = plan.metric;
  const overTime = plan.group_by.length === 1
    && (plan.group_by[0] === "month" || plan.group_by[0] === "week");

  if (plan.group_by.length === 0) {
    const only = rows[0];
    return (
      <p className="font-display text-4xl text-gold-soft">
        {formatValue(metric, only?.value ?? null)}
        <span className="ml-3 align-middle font-sans text-sm text-muted">
          {only ? `${indianDigits(only.orders)} orders` : "no rows"}
        </span>
      </p>
    );
  }

  const tick = (v: number) => formatValue(metric, v, true);
  return (
    <div>
      <div className="mb-2 flex justify-end">
        <button type="button" onClick={() => setAsTable(!asTable)} aria-pressed={asTable}
          className="rounded border border-line px-2 py-1 text-xs text-muted hover:text-text">
          {asTable ? "View as chart" : "View as table"}
        </button>
      </div>
      {asTable ? (
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{humanize(metric ?? "value")} by {plan.group_by.join(" and ")}</caption>
            <thead className="text-left text-muted">
              <tr>
                <th scope="col" className="py-1 pr-3 font-normal">
                  {plan.group_by.map(humanize).join(" · ")}
                </th>
                <th scope="col" className="py-1 pr-3 text-right font-normal">{humanize(metric ?? "value")}</th>
                <th scope="col" className="py-1 text-right font-normal">Orders</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr key={row.label} className="border-t border-line">
                  <td className="py-1 pr-3">{row.label}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">{formatValue(metric, row.value)}</td>
                  <td className="py-1 text-right tabular-nums">{indianDigits(row.orders)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="h-64 w-full" role="img"
          aria-label={`${overTime ? "Line" : "Bar"} chart of ${humanize(metric ?? "value")}. Use "View as table" for the numbers.`}>
          <ResponsiveContainer width="100%" height="100%">
            {overTime ? (
              <LineChart data={data} margin={{ top: 8, right: 12, bottom: 8, left: 8 }}>
                <CartesianGrid stroke="#2c313c" vertical={false} />
                <XAxis dataKey="label" stroke="#a3a6ad" fontSize={12} />
                <YAxis tickFormatter={tick} stroke="#a3a6ad" fontSize={12} width={80} />
                <Tooltip formatter={(v) => formatValue(metric, Number(v))}
                  contentStyle={{ background: "#1f232c", border: "1px solid #2c313c" }} />
                <Line dataKey="value" stroke="#d9ab4f" strokeWidth={2} dot={{ r: 3 }}
                  isAnimationActive={false} />
              </LineChart>
            ) : (
              <BarChart data={data} margin={{ top: 8, right: 12, bottom: 8, left: 8 }}>
                <CartesianGrid stroke="#2c313c" vertical={false} />
                <XAxis dataKey="label" stroke="#a3a6ad" fontSize={12} interval={0}
                  angle={data.length > 6 ? -30 : 0} textAnchor={data.length > 6 ? "end" : "middle"}
                  height={data.length > 6 ? 70 : 30} />
                <YAxis tickFormatter={tick} stroke="#a3a6ad" fontSize={12} width={80} />
                <Tooltip formatter={(v) => formatValue(metric, Number(v))}
                  cursor={{ fill: "rgba(217,171,79,0.08)" }}
                  contentStyle={{ background: "#1f232c", border: "1px solid #2c313c" }} />
                <Bar dataKey="value" fill="#d9ab4f" radius={[3, 3, 0, 0]} isAnimationActive={false} />
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
