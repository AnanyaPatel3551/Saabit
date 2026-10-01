import type { Plan, RunOut } from "../api/types";
import type { Sentence } from "./AskPanel";
import { reasonWithoutSuggestion, suggestedQuestion } from "../lib/plan";
import { ResultChart } from "./ResultChart";
import { VerifiedBadge } from "./VerifiedBadge";

const card = "rounded-xl border bg-panel p-4 sm:p-5";
const chipButton = "rounded-full border border-gold/50 px-3 py-1 text-sm text-gold-soft hover:bg-gold/10";

/**
 * A verified answer: the numbers, badge, chart and caveats show at once; the sentence fills in
 * when the writer finishes (or the template, if it fails).
 */
export function AnswerCard({ answer, sentence, caveats, onEvidence }: {
  answer: RunOut;
  sentence: Sentence;
  caveats: string[];
  onEvidence: () => void;
}) {
  const plan = answer.card.plan;
  const allCaveats = [...new Set([...caveats, ...answer.card.caveats])];
  return (
    <article className={`${card} border-line`}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <p className="font-display text-xl leading-snug text-text" aria-live="polite"
          aria-busy={sentence.status === "pending"}>
          {sentence.status === "pending"
            ? <span className="text-base text-muted">Writing the answer…</span>
            : sentence.text}
        </p>
        <VerifiedBadge verified={answer.verified} />
      </div>
      <ResultChart plan={plan} rows={answer.card.result} />
      {allCaveats.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-muted">
          {allCaveats.map((c) => <li key={c}>Note: {c}</li>)}
        </ul>
      )}
      <div className="mt-3 flex items-center justify-between text-xs text-muted">
        <span>
          {sentence.status === "done" && sentence.source === "template"
            ? "Sentence written from a template." : ""}
        </span>
        <button type="button" onClick={onEvidence} className="text-gold hover:underline">
          Show evidence
        </button>
      </div>
    </article>
  );
}

/** The engines disagreed: amber, both values, and no sentence (FR-6.4). */
export function UnverifiedCard({ answer, onEvidence }: { answer: RunOut; onEvidence: () => void }) {
  return (
    <article className={`${card} border-amber/70`} aria-live="polite">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h3 className="font-display text-lg text-amber">Could not verify</h3>
        <VerifiedBadge verified={false} />
      </div>
      <p className="text-sm text-text">{answer.note}</p>
      {answer.card.mismatches.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-xs text-muted">
          {answer.card.mismatches.map((m) => <li key={m}>{m}</li>)}
        </ul>
      )}
      <button type="button" onClick={onEvidence} className="mt-3 text-xs text-gold hover:underline">
        Show both results in the evidence
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
