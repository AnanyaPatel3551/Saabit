import { fixesCsvUrl } from "../api/client";
import type { DataCheck } from "../api/types";
import { indianDigits } from "../lib/format";

/** What the file can and cannot answer, and what cleaning fixed (FR-3.4, FR-3.5). Shown in
 * the header's "Data check" drawer, which has its own title. */
export function DataCheckPanel({ check }: { check: DataCheck }) {
  const fixedRows = check.fixes.reduce((total, f) => total + f.rows_affected, 0);
  return (
    <section aria-labelledby="check-heading" className="flex flex-col gap-4">
      <h2 id="check-heading" className="sr-only">Data check</h2>
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
        <summary className="cursor-pointer">
          <span aria-hidden="true" className="mr-1 text-amber">⚠</span>
          {check.fixes.length} {check.fixes.length === 1 ? "fix" : "fixes"} applied
          ({indianDigits(fixedRows)} row changes)
        </summary>
        <ul className="mt-2 space-y-1">
          {check.fixes.map((fix) => (
            <li key={fix.rule} className="flex justify-between gap-3">
              <span>{fix.rule}</span>
              <span className="tabular-nums text-muted">{indianDigits(fix.rows_affected)} rows</span>
            </li>
          ))}
        </ul>
        <a href={fixesCsvUrl(check.dataset_id)} download className="mt-3 inline-block text-gold hover:underline">
          Download the fix log (CSV)
        </a>
      </details>

      {check.partial_months.length > 0 && (
        <p className="text-xs text-muted">Partial months: {check.partial_months.join(", ")}.</p>
      )}
      {check.unknown_states.length > 0 && (
        <p className="text-xs text-muted">
          States not recognised: {check.unknown_states.slice(0, 8).join(", ")}
          {check.unknown_states.length > 8 ? ` and ${check.unknown_states.length - 8} more` : ""}.
        </p>
      )}
    </section>
  );
}
