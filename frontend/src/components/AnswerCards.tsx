import { downloadCardRows } from "../api/client";
import type { Plan, ResultRow, RunOut } from "../api/types";
import type { Coverage } from "../lib/coverage";
import { formatValue, indianDigits, keyLabel } from "../lib/format";
import type { Sentence } from "../lib/history";
import type { ReactNode } from "react";
import { CsvDownload } from "./CsvDownload";
import { describePlan, reasonWithoutSuggestion, suggestedQuestion } from "../lib/plan";
import { EvidenceChart, ordersLabel } from "./EvidenceChart";
import { NOT_CHECKED_HELP, VerifiedBadge } from "./VerifiedBadge";

const card = "rounded-xl border bg-panel p-4 sm:p-5";
const chipButton = "rounded-full border border-gold/50 px-3 py-1 text-sm text-gold-soft hover:bg-gold/10";
const PREVIEW_COLUMNS = 8;

/** The number to show big: the single value, the largest group, or the latest period.
 * A latest month the data covers only partly says so: "Jun 2022 (29 of 30 days)". */
export function headline(plan: Plan, rows: ResultRow[], coverage: Coverage = {}):
  { label: string | null; value: string; orders: number } | null {
  if (rows.length === 0) return null;
  if (plan.group_by.length === 0) {
    return { label: null, value: formatValue(plan.metric, rows[0].value), orders: rows[0].orders };
  }
  const overTime = plan.group_by[0] === "month" || plan.group_by[0] === "week";
  const pick = overTime ? rows[rows.length - 1]
    : [...rows].sort((a, b) => (b.value ?? 0) - (a.value ?? 0))[0];
  const label = plan.group_by.map((d) => keyLabel(d, pick[d])).join(" · ");
  const cover = plan.group_by[0] === "month" ? coverage[String(pick.month ?? "")] : undefined;
  const tag = !overTime ? "highest" : cover?.partial ? cover.note : "latest";
  return { label: `${label} (${tag})`,
           value: formatValue(plan.metric, pick.value), orders: pick.orders };
}

/** "Both ways gave 14.2%" or "Both ways gave the same 5 results". */
export function proofText(plan: Plan, rows: ResultRow[]): string {
  if (plan.group_by.length === 0 && rows.length === 1) {
    return `Both ways gave ${formatValue(plan.metric, rows[0].value)}`;
  }
  return `Both ways gave the same ${rows.length} ${rows.length === 1 ? "result" : "results"}`;
}

const NUMBER = /(₹\s?[\d,]+(?:\.\d+)?(?:\s?(?:Cr|lakh))?|\d[\d,]*(?:\.\d+)?%?)/g;

/** The answer sentence with its numbers in bold. */
function Emphasised({ text }: { text: string }) {
  const parts = text.split(NUMBER);
  return <>{parts.map((part, i) => (i % 2 === 1 ? <strong key={i} className="font-semibold">{part}</strong> : part))}</>;
}

/** "Understood as: Revenue · by month · all dates · excluding cancelled orders", with an
 * optional Change button that opens the editable chips (PRD D2: the plan stays editable). */
export function UnderstoodAs({ plan, editor }: { plan: Plan; editor?: Editor }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted">
        <span>Understood as: {describePlan(plan)}</span>
        {editor && (
          <button type="button" onClick={editor.toggle} aria-expanded={editor.open}
            className="min-h-8 text-gold hover:underline">
            {editor.open ? "Done" : "Change"}
          </button>
        )}
      </p>
      {editor?.open && editor.chips}
    </div>
  );
}

export interface Editor {
  open: boolean;
  toggle: () => void;
  chips: ReactNode;
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
  coverage = {}, editor }: {
  answer: RunOut;
  sentence: Sentence;
  caveats: string[];
  onEvidence: () => void;
  collapsed?: boolean;
  onToggle?: () => void;
  coverage?: Coverage;
  editor?: Editor;
}) {
  const plan = answer.card.plan;
  const rows = answer.card.result;
  const top = headline(plan, rows, coverage);
  const allCaveats = [...new Set([...caveats, ...answer.card.caveats])];
  const preview = answer.rows_preview ?? [];
  const columns = preview[0] ? Object.keys(preview[0]).slice(0, PREVIEW_COLUMNS) : [];

  return (
    <article className={`${card} flex flex-col gap-3 border-line`}>
      <UnderstoodAs plan={plan} editor={collapsed ? undefined : editor} />
      <p className="text-lg leading-relaxed text-text" aria-live="polite"
        aria-busy={sentence.status === "pending"}>
        {sentence.status === "pending"
          ? <span className="text-base text-muted">Writing the answer…</span>
          : <Emphasised text={sentence.text ?? ""} />}
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
          Show the details
        </button>
      ) : (
        <>
          <EvidenceChart plan={plan} rows={rows} comparison={answer.comparison} coverage={coverage} />

          {(answer.explanation ?? []).length > 0 && (
            <section aria-label="How we worked it out">
              <h4 className="mb-1 text-xs uppercase tracking-wider text-muted">How we worked it out</h4>
              <ul className="space-y-0.5 text-xs text-text">
                {answer.explanation?.map((line) => <li key={line}>{line}</li>)}
              </ul>
            </section>
          )}

          {preview.length > 0 && (
            <section aria-label="Rows behind this answer">
              <h4 className="mb-1 text-xs uppercase tracking-wider text-muted">
                First {preview.length} of {indianDigits(answer.card.row_count)} rows behind this answer
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
            <section aria-label="Good to know">
              <h4 className="mb-1 text-xs uppercase tracking-wider text-muted">Good to know</h4>
              <ul className="space-y-1 text-xs text-amber">
                {allCaveats.map((c) => <li key={c}>{c}</li>)}
              </ul>
            </section>
          )}

          <div className="flex flex-wrap items-center justify-end gap-3 text-xs text-muted">
            {onToggle && (
              <button type="button" onClick={onToggle} className="min-h-9 hover:text-text">Collapse</button>
            )}
            <button type="button" onClick={onEvidence} className="min-h-9 text-gold hover:underline">
              See how we got this
            </button>
          </div>
        </>
      )}
    </article>
  );
}

/** The two ways disagreed: amber, no number and no sentence. Both results stay available
 * under "Technical details" in the drawer (FR-6.4). */
export function UnverifiedCard({ answer, onEvidence }: { answer: RunOut; onEvidence: () => void }) {
  return (
    <article className={`${card} flex flex-col gap-2 border-amber/70`} aria-live="polite">
      <UnderstoodAs plan={answer.card.plan} />
      <p data-testid="proof-line" className="flex flex-wrap items-center gap-2 text-sm text-text">
        <VerifiedBadge verified={false} />
        <span>{NOT_CHECKED_HELP}</span>
      </p>
      <button type="button" onClick={onEvidence} className="min-h-9 self-start text-xs text-gold hover:underline">
        See the details
      </button>
    </article>
  );
}

/** The question cannot be answered from this file; offer the nearest one that can. */
export function RefusalCard({ plan, onAsk }: { plan: Plan; onAsk: (question: string) => void }) {
  const suggestion = suggestedQuestion(plan.unsupported_reason);
  return (
    <article className={`${card} border-line`} aria-live="polite">
      <h3 className="mb-1 text-lg font-medium text-text">Your file can't answer that</h3>
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
      <h3 className="mb-1 text-lg font-medium text-text">{plan.clarification?.question}</h3>
      <p className="mb-3 text-xs text-muted">Tap one to add it to your question, then press Ask.</p>
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

/** The AI that reads questions is busy: typed questions pause, examples keep working
 * (PRD Degraded mode). Provider details stay out of the UI. */
export function LlmBanner({ reason: _reason }: { reason: string | null }) {
  return (
    <div role="status" className="flex gap-2 rounded-lg border border-amber/60 bg-amber/10 p-3 text-sm text-text">
      <span aria-hidden="true" className="text-amber">⚠</span>
      <p>
        <strong className="font-semibold">Saabit can't read typed questions right now.</strong>{" "}
        The example questions still work, and every number is still worked out exactly. Please
        try typing again in a minute.
      </p>
    </div>
  );
}
