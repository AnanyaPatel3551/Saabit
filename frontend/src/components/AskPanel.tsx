import { useRef, useState, type FormEvent } from "react";
import { ApiError, planQuestion, runPlan, writeSentence } from "../api/client";
import type { Card, Plan, RunOut } from "../api/types";
import { EXAMPLES } from "../lib/plan";
import {
  AnswerCard, ClarificationCard, LlmBanner, RefusalCard, UnverifiedCard,
} from "./AnswerCards";
import { PlanChips } from "./PlanChips";

type View =
  | { kind: "idle" }
  | { kind: "loading"; label: string }
  | { kind: "answer"; run: RunOut; caveats: string[]; sentence: Sentence }
  | { kind: "clarify"; plan: Plan; question: string }
  | { kind: "refuse"; plan: Plan }
  | { kind: "error"; message: string };

/** The answer sentence: pending while the writer works, then the LLM's or the template. */
export type Sentence = { status: "pending" } | { status: "done"; text: string | null; source: string };

/** After this long the template is shown instead of waiting for the writer. */
export const SENTENCE_TIMEOUT_MS = 20_000;

/**
 * Centre panel. Owns /plan (typed questions), /run (planned questions, example chips and
 * edited plan chips; returns the numbers first) and the card sentence call that follows.
 * Chip edits never go back through /plan.
 */
export function AskPanel({ datasetId, llmDown, llmReason, onLlmChange, onEvidence }: {
  datasetId: string;
  llmDown: boolean;
  llmReason: string | null;
  onLlmChange: (down: boolean, reason: string | null) => void;
  onEvidence: (card: Card) => void;
}) {
  const [question, setQuestion] = useState("");
  const [view, setView] = useState<View>({ kind: "idle" });
  const [chipPlan, setChipPlan] = useState<Plan | null>(null);
  const latest = useRef(0);  // ignores sentences that arrive for an older answer
  const busy = view.kind === "loading";

  async function run(plan: Plan, asked: string, caveats: string[] = []) {
    const turn = ++latest.current;
    setChipPlan(plan);
    setView({ kind: "loading", label: "Computing with SQL and pandas…" });
    let result: RunOut;
    try {
      result = await runPlan(datasetId, plan);
    } catch (error) {
      setView({ kind: "error", message: messageOf(error) });
      return;
    }
    setChipPlan(result.card.plan);
    const template: Sentence = { status: "done", text: result.sentence, source: result.source };
    const waitForWriter = result.sentence_status === "pending" && !llmDown;
    setView({ kind: "answer", run: result, caveats,
              sentence: waitForWriter ? { status: "pending" } : template });
    if (!waitForWriter) return;
    const finished = await sentenceOrTemplate(result, asked, template);
    if (turn === latest.current) {
      setView((now) => now.kind === "answer" ? { ...now, sentence: finished } : now);
    }
  }

  async function ask(text: string) {
    const asked = text.trim();
    if (!asked) return;
    setQuestion(asked);
    setChipPlan(null);
    setView({ kind: "loading", label: "Understanding the question…" });
    try {
      const planned = await planQuestion(datasetId, asked);
      if (llmDown) onLlmChange(false, null);
      const plan = planned.plan;
      if (plan.status === "needs_clarification") setView({ kind: "clarify", plan, question: asked });
      else if (plan.status === "unsupported") setView({ kind: "refuse", plan });
      else await run(plan, asked, planned.caveats);
    } catch (error) {
      if (error instanceof ApiError && error.code === "llm_unavailable") {
        onLlmChange(true, error.message);
      }
      setView({ kind: "error", message: messageOf(error) });
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void ask(question);
  }

  return (
    <section aria-labelledby="ask-heading" className="flex flex-col gap-4">
      <h2 id="ask-heading" className="font-display text-2xl text-gold-soft">Ask</h2>
      {llmDown && <LlmBanner reason={llmReason} />}

      <form onSubmit={submit} className="flex gap-2">
        <label htmlFor="question" className="sr-only">Your question</label>
        <input id="question" value={question} onChange={(e) => setQuestion(e.target.value)}
          maxLength={500} placeholder="e.g. rajsthan ka cancellation kitna hai"
          className="min-w-0 flex-1 rounded-lg border border-line bg-raised px-3 py-2 text-text placeholder:text-muted" />
        <button type="submit" disabled={busy || !question.trim()}
          className="rounded-lg bg-gold px-4 py-2 font-medium text-ink hover:bg-gold-soft disabled:opacity-50">
          Ask
        </button>
      </form>

      <div className="flex flex-wrap gap-2" aria-label="Example questions" role="group">
        {EXAMPLES.map((example) => (
          <button key={example.question} type="button" disabled={busy}
            onClick={() => { setQuestion(example.question); void run(example.plan, example.question); }}
            className="rounded-full border border-line px-3 py-1 text-sm text-muted hover:border-gold/60 hover:text-text">
            {example.question}
          </button>
        ))}
      </div>

      {view.kind === "loading" && <p role="status" className="text-sm text-muted">{view.label}</p>}
      {view.kind === "error" && (
        <p role="alert" className="rounded-lg border border-bad/60 bg-bad/10 p-3 text-sm text-text">
          {view.message}
        </p>
      )}
      {view.kind === "clarify" && (
        <ClarificationCard plan={view.plan}
          onChoose={(option) => void ask(`${view.question} (${option})`)} />
      )}
      {view.kind === "refuse" && <RefusalCard plan={view.plan} onAsk={(q) => void ask(q)} />}
      {view.kind === "answer" && (view.run.verified
        ? <AnswerCard answer={view.run} sentence={view.sentence} caveats={view.caveats}
            onEvidence={() => onEvidence(view.run.card)} />
        : <UnverifiedCard answer={view.run} onEvidence={() => onEvidence(view.run.card)} />)}

      {chipPlan && (
        <PlanChips plan={chipPlan} disabled={busy} onChange={(plan) => void run(plan, "")} />
      )}
    </section>
  );
}

/** The LLM sentence, or the template if the writer fails or takes too long. */
async function sentenceOrTemplate(run: RunOut, asked: string, template: Sentence): Promise<Sentence> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SENTENCE_TIMEOUT_MS);
  try {
    const written = await writeSentence(run.card.card_id, asked, controller.signal);
    return written.sentence ? { status: "done", text: written.sentence, source: written.source }
      : template;
  } catch {
    return template;
  } finally {
    clearTimeout(timer);
  }
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}
