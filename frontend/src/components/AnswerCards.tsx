import { downloadCardRows } from "../api/client";
import type { Plan, ResultRow, RunOut } from "../api/types";
import { formatValue, indianDigits, keyLabel } from "../lib/format";
import type { Sentence } from "../lib/history";
import { CsvDownload } from "./CsvDownload";
import { reasonWithoutSuggestion, suggestedQuestion } from "../lib/plan";
import { EvidenceChart, ordersLabel } from "./EvidenceChart";
import { VerifiedBadge } from "./VerifiedBadge";

const card = "rounded-xl border bg-panel p-4 sm:p-5";
const chipButton = "rounded-full border border-gold/50 px-3 py-1 text-sm text-gold-soft hover:bg-gold/10";
const PREVIEW_COLUMNS = 8;

/** The number to show big: the single value, the largest group, or the latest period. */
function headline(plan: Plan, rows: ResultRow[]): { label: string | null; value: string; orders: number } | null {
  if (rows.length === 0) return null;
  if (plan.group_by.length === 0) {
    return { label: null, value: formatValue(plan.metric, rows[0].value), orders: rows[0].orders };
  }
  const overTime = plan.group_by[0] === "month" || plan.group_by[0] === "week";
  const pick = overTime ? rows[rows.length - 1]
    : [...rows].sort((a, b) => (b.value ?? 0) - (a.value ?? 0))[0];
  const label = plan.group_by.map((d) => keyLabel(d, pick[d])).join(" · ");
  return { label: overTime ? `${label} (latest)` : `${label} (highest)`,
           value: formatValue(plan.metric, pick.value), orders: pick.orders };
}

/** "SQL and pandas both gave 14.2%" or "...the same 5 results". */
export function proofText(plan: Plan, rows: ResultRow[]): string {
  if (plan.group_by.length === 0 && rows.length === 1) {
    return `SQL and pandas both gave ${formatValue(plan.metric, rows[0].value)}`;
  }
  return `SQL and pandas gave the same ${rows.length} ${rows.length === 1 ? "result" : "results"}`;
}

function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "yes" : "no";
  const text = String(value);
  return /^\d{4}-\d{2}-\d{2}T/.test(text) ? text.slice(0, 10) : text;
}

/**
 * A verified answer with its evidence: sentence, the big number, the proof line, a chart,
 * how it was calculated, the first source rows and the caveats. Collapsed (older answers in
 * the thread) it keeps only the sentence, the number and the proof line.
 */
export function AnswerCard({ answer, sentence, caveats, onEvidence, collapsed, onToggle,
  partialMonths = [] }: {
  answer: RunOut;
  sentence: Sentence;
  caveats: string[];
  onEvidence: () => void;
  collapsed?: boolean;
  onToggle?: () => void;
  partialMonths?: string[];
}) {
  const plan = answer.card.plan;
  const rows = answer.card.result;
  const top = headline(plan, rows);
  const allCaveats = [...new Set([...caveats, ...answer.card.caveats])];
  const preview = answer.rows_preview ?? [];
  const columns = preview[0] ? Object.keys(preview[0]).slice(0, PREVIEW_COLUMNS) : [];

  return (
    <article className={`${card} flex flex-col gap-3 border-line`}>
      <p className="font-display text-xl leading-snug text-text" aria-live="polite"
        aria-busy={sentence.status === "pending"}>
        {sentence.status === "pending"
          ? <span className="text-base text-muted">Writing the answer…</span>
          : sentence.text}
      </p>

      {top ? (
        <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="font-display text-4xl tabular-nums text-gold-soft">{top.value}</span>
          <span className="text-sm text-muted">
            {top.label ? `${top.label} · ` : ""}{indianDigits(top.orders)} {ordersLabel(plan.metric)}
          </span>
        </p>
      ) : (
        <p className="text-sm text-muted">No orders match this question.</p>
      )}

      <p data-testid="proof-line" className="flex flex-wrap items-center gap-2 text-sm text-text">
        <VerifiedBadge verified />
        <span>{proofText(plan, rows)}</span>
      </p>

      {collapsed ? (
        <button type="button" onClick={onToggle} className="min-h-9 self-start text-xs text-gold hover:underline">
          Show the evidence
        </button>
      ) : (
        <>
          <EvidenceChart plan={plan} rows={rows} comparison={answer.comparison}
            partialMonths={partialMonths} compact />

          {(answer.explanation ?? []).length > 0 && (
            <section aria-label="How this was calculated">
              <h4 className="mb-1 text-xs uppercase tracking-wider text-muted">How this was calculated</h4>
              <ul className="space-y-0.5 text-xs text-text">
                {answer.explanation?.map((line) => <li key={line}>{line}</li>)}
              </ul>
            </section>
          )}

          {preview.length > 0 && (
            <section aria-label="Source rows">
              <h4 className="mb-1 text-xs uppercase tracking-wider text-muted">
                First {preview.length} of {indianDigits(answer.card.row_count)} source rows
              </h4>
              <div className="overflow-x-auto rounded border border-line">
                <table className="w-full text-[11px]">
                  <thead className="bg-raised text-left text-muted">
                    <tr>{columns.map((c) => <th key={c} scope="col" className="px-2 py-1 font-normal">{c}</th>)}</tr>
                  </thead>
                  <tbody>
                    {preview.map((row, i) => (
                      <tr key={i} className="border-t border-line">
                        {columns.map((c) => <td key={c} className="whitespace-nowrap px-2 py-1">{cell(row[c])}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <CsvDownload label={`Download all ${indianDigits(answer.card.row_count)} rows (CSV)`}
                download={() => downloadCardRows(answer.card.card_id)}
                className="mt-1 inline-block min-h-9 text-xs text-gold hover:underline" />
            </section>
          )}

          {allCaveats.length > 0 && (
            <ul className="space-y-1 text-xs text-amber">
              {allCaveats.map((c) => <li key={c}>Note: {c}</li>)}
            </ul>
          )}

          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
            <span>
              {sentence.status === "done" && sentence.source === "template"
                ? "Sentence written from a template." : ""}
            </span>
            <span className="flex items-center gap-3">
              {onToggle && (
                <button type="button" onClick={onToggle} className="min-h-9 hover:text-text">Collapse</button>
              )}
              <button type="button" onClick={onEvidence} className="min-h-9 text-gold hover:underline">
                Full evidence: SQL · pandas · plan
              </button>
            </span>
          </div>
        </>
      )}
    </article>
  );
}

/** "SQL: ₹2,39,53,534. pandas: ₹2,41,93,069." from the could-not-verify note. */
function bothValues(note: string | null): string {
  const match = note?.match(/SQL: (.+?)\. pandas: (.+?)\.$/);
  return match ? `SQL gave ${match[1]}; pandas gave ${match[2]}` : "SQL and pandas gave different results";
}

/** The engines disagreed: amber, both values, and no sentence (FR-6.4). */
export function UnverifiedCard({ answer, onEvidence }: { answer: RunOut; onEvidence: () => void }) {
  return (
    <article className={`${card} flex flex-col gap-2 border-amber/70`} aria-live="polite">
      <h3 className="font-display text-lg text-amber">Could not verify</h3>
      <p data-testid="proof-line" className="flex flex-wrap items-center gap-2 text-sm text-text">
        <VerifiedBadge verified={false} />
        <span>{bothValues(answer.note)}</span>
      </p>
      <p className="text-xs text-muted">{answer.note}</p>
      {answer.card.mismatches.length > 0 && (
        <ul className="list-disc pl-5 text-xs text-muted">
          {answer.card.mismatches.map((m) => <li key={m}>{m}</li>)}
        </ul>
      )}
      <button type="button" onClick={onEvidence} className="min-h-9 self-start text-xs text-gold hover:underline">
        Full evidence: both results, SQL · pandas · plan
      </button>
    </article>
  );
}

/** The question cannot be answered from this file; offer the nearest one that can. */
export function RefusalCard({ plan, onAsk }: { plan: Plan; onAsk: (question: string) => void }) {
  const suggestion = suggestedQuestion(plan.unsupported_reason);
  return (
    <article className={`${card} border-line`} aria-live="polite">
      <h3 className="mb-1 font-display text-lg text-text">This file cannot answer that</h3>
      <p className="text-sm text-muted">
        {reasonWithoutSuggestion(plan.unsupported_reason) || "The question is outside what this data covers."}
      </p>
      {suggestion && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted">Try instead:</span>
          <button type="button" className={chipButton} onClick={() => onAsk(suggestion)}>
            {suggestion}
          </button>
        </div>
      )}
    </article>
  );
}

/** The planner needs one choice from the user before it can plan. */
export function ClarificationCard({ plan, onChoose }: {
  plan: Plan;
  onChoose: (option: string) => void;
}) {
  return (
    <article className={`${card} border-line`} aria-live="polite">
      <h3 className="mb-3 font-display text-lg text-text">{plan.clarification?.question}</h3>
      <div className="flex flex-wrap gap-2">
        {plan.clarification?.options.map((option) => (
          <button key={option} type="button" className={chipButton} onClick={() => onChoose(option)}>
            {option}
          </button>
        ))}
      </div>
    </article>
  );
}

/** The planner's LLM is down: typed questions pause, chips keep working (PRD Degraded mode). */
export function LlmBanner({ reason }: { reason: string | null }) {
  return (
    <div role="status" className="flex gap-2 rounded-lg border border-amber/60 bg-amber/10 p-3 text-sm text-text">
      <span aria-hidden="true" className="text-amber">⚠</span>
      <p>
        <strong className="font-semibold">The question planner is unavailable right now.</strong>{" "}
        {reason ? `${reason} ` : ""}The example chips and the plan chips still work, because
        they skip the planner. Typed questions may fail until it is back.
      </p>
    </div>
  );
}
