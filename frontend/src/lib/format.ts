// Display formatting only, in the same Indian style as the backend templates.
// Values themselves always come from the API; nothing here computes a metric.

import type { MetricName } from "../api/types";

export function indianDigits(value: number): string {
  const sign = value < 0 ? "-" : "";
  const digits = Math.round(Math.abs(value)).toString();
  if (digits.length <= 3) return sign + digits;
  let head = digits.slice(0, -3);
  const pairs: string[] = [];
  while (head.length > 2) {
    pairs.unshift(head.slice(-2));
    head = head.slice(0, -2);
  }
  if (head) pairs.unshift(head);
  return `${sign}${pairs.join(",")},${digits.slice(-3)}`;
}

export function formatInr(value: number): string {
  if (Math.abs(value) >= 1000 || Number.isInteger(value)) return `₹${indianDigits(value)}`;
  return `₹${value.toFixed(2)}`;
}

export function formatShortInr(value: number): string {
  if (Math.abs(value) >= 1e7) return `₹${(value / 1e7).toFixed(2)} Cr`;
  if (Math.abs(value) >= 1e5) return `₹${(value / 1e5).toFixed(2)} lakh`;
  return formatInr(value);
}

export function formatValue(metric: MetricName | null, value: number | null | undefined,
  short = false): string {
  if (value === null || value === undefined) return "—";
  if (metric === "revenue" || metric === "aov") return short ? formatShortInr(value) : formatInr(value);
  if (metric === "cancellation_rate") return `${value.toFixed(1)}%`;
  return indianDigits(value);
}

export function monthLabel(key: string): string {
  const [year, month] = key.split("-").map(Number);
  return new Date(year, month - 1, 1).toLocaleString("en-IN", { month: "short", year: "numeric" });
}

export function keyLabel(dimension: string, key: unknown): string {
  if (key === null || key === undefined) return "(blank)";
  const text = String(key);
  if (dimension === "month") return monthLabel(text);
  if (dimension === "week") return `wk ${text}`;
  return text;
}
