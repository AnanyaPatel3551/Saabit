import { downloadFixes } from "../api/client";
import type { DataCheck } from "../api/types";
import { monthCoverage, partialOnly } from "../lib/coverage";
import { indianDigits, monthLabel } from "../lib/format";
import { CsvDownload } from "./CsvDownload";

/** One plain sentence per kind of clean-up (rules from backend core/clean.py). */
function cleanUpSentence(rule: string, entries: number, rows: number): string | null {
  const n = indianDigits(entries);
  const r = indianDigits(rows);
  switch (rule) {
    case "state_normalised": return `Merged ${n} different spellings of state names into one name each (${r} rows).`;
    case "city_normalised": return `Tidied ${n} city names that differed only in capitals or spaces (${r} rows).`;
    case "amount_cleaned": return `Read ${r} amounts written with ₹ signs or commas as plain numbers.`;
    case "amount_unparseable": return `Left out ${r} rows whose amount could not be read as a number.`;
    case "date_unparseable": return `Left out ${r} rows whose date could not be read.`;
    case "duplicate_row": return `Removed ${r} rows that were exact copies of another row.`;
    case "qty_not_integer": return `Noted ${r} rows where the quantity is not a whole number.`;
    case "date_order": return "Worked out which way round your dates are written (day or month first).";
    case "partial_month":
    case "state_unknown": return null;  // shown under "Good to know"
    default: return `${rule.replace(/_/g, " ")}: ${r} rows.`;
  }
}

/** Left panel: what the file can and cannot answer, what we cleaned up and what is good to
 * know (FR-3.4, FR-3.5). */
export function DataCheckPanel({ check }: { check: DataCheck }) {
  const cleanUps = check.fixes
    .map((f) => cleanUpSentence(f.rule, f.entries, f.rows_affected))
    .filter((s): s is string => s !== null);
  const partial = partialOnly(monthCoverage(check.date_min, check.date_max));
  return (
    <section aria-labelledby="check-heading" className="flex flex-col gap-4">
      <h2 id="check-heading" className="font-display text-2xl text-gold-soft">Your data</h2>
      <p className="text-sm text-muted">
        {indianDigits(check.rows_in)} rows read, {indianDigits(check.rows_out)} kept after cleaning.
      </p>

      <div>
        <h3 className="mb-2 text-sm font-semibold text-text">Can answer</h3>
        <ul className="space-y-1 text-sm">
          {check.capability.can_answer.map((item) => (
            <li key={item.topic} className="flex gap-2">
              <span aria-hidden="true" className="text-ok">✓</span>
              <span><span className="sr-only">Can answer: </span>{item.topic}</span>
            </li>
          ))}
        </ul>
      </div>

      {check.capability.cannot_answer.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-text">Cannot answer</h3>
          <ul className="space-y-2 text-sm">
            {check.capability.cannot_answer.map((item) => (
              <li key={item.topic} className="flex gap-2">
                <span aria-hidden="true" className="text-bad">✗</span>
                <span>
                  <span className="sr-only">Cannot answer: </span>{item.topic}
                  <span className="block text-xs text-muted">{item.reason}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <details className="rounded-lg border border-line bg-raised p-3 text-sm">
        <summary className="cursor-pointer">What we cleaned up ({cleanUps.length})</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {cleanUps.length === 0 && <li className="text-muted">Nothing needed cleaning.</li>}
          {cleanUps.map((line) => <li key={line}>{line}</li>)}
        </ul>
        <CsvDownload label="Download every change (CSV)" download={() => downloadFixes(check.dataset_id)}
          className="mt-3 inline-block text-gold hover:underline" />
      </details>

      {(partial.length > 0 || check.unknown_states.length > 0) && (
        <div>
          <h3 className="mb-1 text-sm font-semibold text-text">Good to know</h3>
          <ul className="list-disc space-y-1 pl-5 text-xs text-muted">
            {partial.map((m) => (
              <li key={m.month}>
                {monthLabel(m.month)} has {m.days === 1 ? "only 1 day" : `${m.days} of ${m.of} days`} of
                data, so it is not comparable to full months.
              </li>
            ))}
            {check.unknown_states.length > 0 && (
              <li>
                We didn't recognise these state names, so we kept them as written:{" "}
                {check.unknown_states.slice(0, 8).join(", ")}
                {check.unknown_states.length > 8 ? ` and ${check.unknown_states.length - 8} more` : ""}.
              </li>
            )}
          </ul>
        </div>
      )}
    </section>
  );
}
