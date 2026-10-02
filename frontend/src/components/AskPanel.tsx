import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, planQuestion, runPlan, writeSentence } from "../api/client";
import type { Card, Plan, RunOut } from "../api/types";
import {
  clearHistory, loadHistory, newEntryId, saveHistory, type HistoryEntry, type Sentence,
} from "../lib/history";
import { EXAMPLES } from "../lib/plan";
import {
  AnswerCard, ClarificationCard, LlmBanner, RefusalCard, UnverifiedCard,
} from "./AnswerCards";
import { PlanChips, type DataRange } from "./PlanChips";

export type { Sentence } from "../lib/history";

/** What is happening right now, above the thread of past answers. */
type Status =
  | { kind: "idle" }
  | { kind: "loading"; label: string }
  | { kind: "clarify"; plan: Plan; question: string }
  | { kind: "error"; message: string };

/** After this long the template is shown instead of waiting for the writer. */
export const SENTENCE_TIMEOUT_MS = 10_000;

/**
 * Centre panel. Owns /plan (typed questions), /run (planned questions, example chips and
 * edited plan chips; returns the numbers first) and the card sentence call that follows.
 * Chip edits never go back through /plan. Answers stay as a thread, newest first, saved in
 * this browser per dataset.
 */
export function AskPanel({ datasetId, llmDown, llmReason, onLlmChange, onEvidence, range,
  partialMonths = [] }: {
  datasetId: string;
  range?: DataRange;
  partialMonths?: string[];
  llmDown: boolean;
  llmReason: string | null;
  onLlmChange: (down: boolean, reason: string | null) => void;
  onEvidence: (card: Card) => void;
}) {
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [entries, setEntries] = useState<HistoryEntry[]>(() => loadHistory(datasetId));
  const [expanded, setExpanded] = useState<Set<string>>(new Set());  // older answers opened
  const [chipPlan, setChipPlan] = useState<Plan | null>(() => newestPlan(loadHistory(datasetId)));
  const busy = status.kind === "loading";
  const firstUse = entries.length === 0 && status.kind === "idle";
  const mounted = useRef(true);
  const questionBox = useRef<HTMLInputElement>(null);

  useEffect(() => () => { mounted.current = false; }, []);
  useEffect(() => saveHistory(datasetId, entries), [datasetId, entries]);

  function add(entry: HistoryEntry) {
    setEntries((now) => [entry, ...now]);
  }

  async function run(plan: Plan, asked: string, caveats: string[] = []) {
    setChipPlan(plan);
    setStatus({ kind: "loading", label: "Computing with SQL and pandas…" });
    let result: RunOut;
    try {
      result = await runPlan(datasetId, plan);
    } catch (error) {
      setStatus({ kind: "error", message: messageOf(error) });
      return;
    }
    setChipPlan(result.card.plan);
    setStatus({ kind: "idle" });
    const template: Sentence = { status: "done", text: result.sentence, source: result.source };
    const waitForWriter = result.sentence_status === "pending" && !llmDown;
    const id = newEntryId();
    add({ id, question: asked || "Edited plan", askedAt: new Date().toISOString(), run: result,
          caveats, sentence: waitForWriter ? { status: "pending" } : template });
    if (!waitForWriter) return;
    const finished = await sentenceOrTemplate(result, asked, template);
    if (mounted.current) {
      setEntries((now) => now.map((e) => (e.id === id ? { ...e, sentence: finished } : e)));
    }
  }

  async function ask(text: string) {
    const asked = text.trim();
    if (!asked) return;
    setQuestion(asked);
    setStatus({ kind: "loading", label: "Understanding the question…" });
    try {
      const planned = await planQuestion(datasetId, asked);
      if (llmDown) onLlmChange(false, null);
      const plan = planned.plan;
      if (plan.status === "needs_clarification") {
        setStatus({ kind: "clarify", plan, question: asked });
      } else if (plan.status === "unsupported") {
        setStatus({ kind: "idle" });
        add({ id: newEntryId(), question: asked, askedAt: new Date().toISOString(),
              caveats: [], refusal: plan });
      } else {
        await run(plan, asked, planned.caveats);
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "llm_unavailable") {
        onLlmChange(true, error.message);
      }
      setStatus({ kind: "error", message: messageOf(error) });
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!question.trim()) {
      questionBox.current?.focus();  // nothing to ask yet: point at the box instead
      return;
    }
    void ask(question);
  }

  function clear() {
    clearHistory(datasetId);
    setEntries([]);
    setChipPlan(null);
    setStatus({ kind: "idle" });
  }

  return (
    <section aria-labelledby="ask-heading" className="flex flex-col gap-4">
      <h2 id="ask-heading" className="font-display text-2xl text-gold-soft">Ask</h2>
      {llmDown && <LlmBanner reason={llmReason} />}

      <form onSubmit={submit} className="flex gap-2">
        <label htmlFor="question" className="sr-only">Your question</label>
        <input id="question" ref={questionBox} value={question} onChange={(e) => setQuestion(e.target.value)}
          maxLength={500} placeholder="e.g. rajsthan ka cancellation kitna hai"
          className="min-h-10 min-w-0 flex-1 rounded-lg border border-line bg-raised px-3 py-2 text-text placeholder:text-muted" />
        {/* Always gold. Empty box: a click focuses the box. While asking: ignores clicks. */}
        <button type="submit" aria-disabled={busy}
          className={`min-h-10 rounded-lg border border-gold bg-gold px-4 py-2 font-medium text-ink hover:bg-gold-soft ${
            busy ? "cursor-wait" : ""}`}>
          {busy ? "Asking…" : "Ask"}
        </button>
      </form>

      {firstUse && <p className="text-sm text-text">Try one of these, or type your own.</p>}
      <div className="flex flex-wrap gap-2" aria-label="Example questions" role="group">
        {EXAMPLES.map((example) => (
          <button key={example.question} type="button" disabled={busy}
            onClick={() => { setQuestion(example.question); void run(example.plan, example.question); }}
            className="min-h-10 rounded-full border border-line px-3 py-1 text-sm text-muted hover:border-gold/60 hover:text-text">
            {example.question}
          </button>
        ))}
      </div>
      {firstUse && (
        <p className="border-l-2 border-gold/60 pl-3 text-xs text-muted">
          Verified means two separate calculations, SQL and pandas, gave the same result.
        </p>
      )}

      {status.kind === "loading" && <p role="status" className="text-sm text-muted">{status.label}</p>}
      {status.kind === "error" && (
        <p role="alert" className="rounded-lg border border-bad/60 bg-bad/10 p-3 text-sm text-text">
          {status.message}
        </p>
      )}
      {status.kind === "clarify" && (
        <ClarificationCard plan={status.plan}
          onChoose={(option) => void ask(`${status.question} (${option})`)} />
      )}

      {chipPlan && entries[0]?.run && (
        <PlanChips plan={chipPlan} disabled={busy} range={range}
          onChange={(plan) => void run(plan, "")} />
      )}

      {entries.length > 0 && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs uppercase tracking-wider text-muted">
              Your questions ({entries.length})
            </h3>
            <button type="button" onClick={clear}
              className="min-h-10 rounded px-2 text-xs text-muted hover:text-text">
              Clear
            </button>
          </div>
          <ol className="flex flex-col gap-4" aria-label="Question history, newest first">
            {entries.map((entry, index) => (
              <li key={entry.id} className="flex flex-col gap-2">
                <p className="text-sm text-muted">
                  <span className="sr-only">Question: </span>{entry.question}
                </p>
                <EntryCard entry={entry} onEvidence={onEvidence} onAsk={(q) => void ask(q)}
                  partialMonths={partialMonths}
                  collapsed={index > 0 && !expanded.has(entry.id)}
                  onToggle={index > 0 ? () => setExpanded((now) => {
                    const next = new Set(now);
                    if (next.has(entry.id)) next.delete(entry.id); else next.add(entry.id);
                    return next;
                  }) : undefined} />
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}

function EntryCard({ entry, onEvidence, onAsk, collapsed, onToggle, partialMonths }: {
  entry: HistoryEntry;
  onEvidence: (card: Card) => void;
  onAsk: (question: string) => void;
  collapsed: boolean;
  onToggle?: () => void;
  partialMonths: string[];
}) {
  if (entry.refusal) return <RefusalCard plan={entry.refusal} onAsk={onAsk} />;
  const run = entry.run;
  if (!run) return null;
  // the drawer draws the same chart, so the comparison travels with the card
  const open = () => onEvidence({ ...run.card, comparison: run.comparison ?? null });
  if (!run.verified) return <UnverifiedCard answer={run} onEvidence={open} />;
  const sentence = entry.sentence ?? { status: "done", text: run.sentence, source: run.source };
  return <AnswerCard answer={run} sentence={sentence} caveats={entry.caveats} onEvidence={open}
    collapsed={collapsed} onToggle={onToggle} partialMonths={partialMonths} />;
}

function newestPlan(entries: HistoryEntry[]): Plan | null {
  return entries[0]?.run?.card.plan ?? null;
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
