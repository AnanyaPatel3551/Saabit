import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ApiError, planQuestion, runPlan, writeSentence } from "../api/client";
import type { Card, Plan, RunOut } from "../api/types";
import type { Coverage } from "../lib/coverage";
import {
  clearHistory, loadHistory, newEntryId, saveHistory, type HistoryEntry, type Sentence,
} from "../lib/history";
import { EXAMPLES } from "../lib/plan";
import {
  AnswerCard, ClarificationCard, LlmBanner, RefusalCard, UnverifiedCard,
} from "./AnswerCards";
import { friendlyError, ErrorNote } from "./ErrorNote";
import { PlanChips, type DataRange } from "./PlanChips";

export type { Sentence } from "../lib/history";

/** The question being worked on right now, shown as the newest card in the thread. */
type Status =
  | { kind: "idle" }
  | { kind: "loading"; question: string; label: string }
  | { kind: "clarify"; plan: Plan; question: string }
  | { kind: "error"; question: string; message: string; requestId: string | null };

/** After this long the template is shown instead of waiting for the writer. */
export const SENTENCE_TIMEOUT_MS = 10_000;

/**
 * Centre panel. Chips only fill the question box; a question is sent only with Ask or Enter
 * (Shift+Enter starts a new line), and the box is cleared once it is sent. An example
 * question sent unchanged runs its ready plan, so it works even when the AI is busy. Typed
 * questions go through /plan, then /run returns the numbers first and the sentence follows.
 * Answers stay as a thread, newest first, saved in this browser per dataset.
 */
export function AskPanel({ datasetId, llmDown, llmReason, onLlmChange, onEvidence, range,
  coverage = {}, fill }: {
  datasetId: string;
  range?: DataRange;
  coverage?: Coverage;
  llmDown: boolean;
  llmReason: string | null;
  onLlmChange: (down: boolean, reason: string | null) => void;
  onEvidence: (card: Card) => void;
  /** Text to put in the box from outside (month chips); a new object each time. */
  fill?: { text: string } | null;
}) {
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [entries, setEntries] = useState<HistoryEntry[]>(() => loadHistory(datasetId));
  const [expanded, setExpanded] = useState<Set<string>>(new Set());  // older answers opened
  const [editing, setEditing] = useState(false);
  const busy = status.kind === "loading";
  const empty = !question.trim();
  const mounted = useRef(true);
  const questionBox = useRef<HTMLTextAreaElement>(null);
  const newest = useRef<HTMLLIElement>(null);

  useEffect(() => () => { mounted.current = false; }, []);
  useEffect(() => saveHistory(datasetId, entries), [datasetId, entries]);
  useEffect(() => {
    newest.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [status.kind, entries[0]?.id]);
  useEffect(() => { if (fill) fillBox(fill.text); }, [fill]);  // eslint-disable-line react-hooks/exhaustive-deps

  /** Put text in the box and the cursor at its end; never sends anything. */
  function fillBox(text: string) {
    setQuestion(text);
    requestAnimationFrame(() => {
      const box = questionBox.current;
      if (!box) return;
      box.focus();
      box.setSelectionRange(text.length, text.length);
    });
  }

  function add(entry: HistoryEntry) {
    setEntries((now) => [entry, ...now]);
    setExpanded(new Set());
  }

  async function run(plan: Plan, asked: string, caveats: string[] = []) {
    setEditing(false);
    setStatus({ kind: "loading", question: asked || "Changed question", label: "Working out the numbers…" });
    let result: RunOut;
    try {
      result = await runPlan(datasetId, plan);
    } catch (error) {
      setStatus({ kind: "error", question: asked, ...friendlyError(error) });
      return;
    }
    setStatus({ kind: "idle" });
    const template: Sentence = { status: "done", text: result.sentence, source: result.source };
    const waitForWriter = result.sentence_status === "pending" && !llmDown;
    const id = newEntryId();
    add({ id, question: asked || "Changed question", askedAt: new Date().toISOString(), run: result,
          caveats, sentence: waitForWriter ? { status: "pending" } : template });
    if (!waitForWriter) return;
    const finished = await sentenceOrTemplate(result, asked, template);
    if (mounted.current) {
      setEntries((now) => now.map((e) => (e.id === id ? { ...e, sentence: finished } : e)));
    }
  }

  async function ask(asked: string) {
    setStatus({ kind: "loading", question: asked, label: "Understanding the question…" });
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
      setStatus({ kind: "error", question: asked, ...friendlyError(error) });
    }
  }

  function send() {
    if (busy || empty) {
      questionBox.current?.focus();
      return;
    }
    const asked = question.trim();
    setQuestion("");  // one rule: the box is cleared once a question is sent
    const example = EXAMPLES.find((e) => e.question.toLowerCase() === asked.toLowerCase());
    if (example) void run(example.plan, example.question);
    else void ask(asked);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    send();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send();
    }
  }

  function clear() {
    clearHistory(datasetId);
    setEntries([]);
    setStatus({ kind: "idle" });
  }

  const toggle = (id: string) => setExpanded((now) => {
    const next = new Set(now);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  return (
    <section aria-labelledby="ask-heading" className="flex flex-col gap-4">
      <h2 id="ask-heading" className="font-display text-2xl text-gold-soft">Ask</h2>
      {llmDown && <LlmBanner reason={llmReason} />}

      <form onSubmit={submit} className="flex items-start gap-2">
        <label htmlFor="question" className="sr-only">Your question</label>
        <textarea id="question" ref={questionBox} value={question} rows={1}
          onChange={(e) => setQuestion(e.target.value)} onKeyDown={onKeyDown}
          maxLength={500} placeholder="e.g. rajsthan ka cancellation kitna hai"
          className="min-h-10 min-w-0 flex-1 resize-none rounded-lg border border-line bg-raised px-3 py-2 text-text placeholder:text-muted" />
        {/* Gold at all times (as asked); it does nothing while the box is empty or a question is running. */}
        <button type="submit" aria-disabled={busy || empty}
          className={`min-h-10 rounded-lg border border-gold bg-gold px-4 py-2 font-medium text-ink hover:bg-gold-soft ${
            busy ? "cursor-wait" : ""}`}>
          {busy ? "Asking…" : "Ask"}
        </button>
      </form>

      <div className="flex flex-wrap gap-2" aria-label="Example questions" role="group">
        {EXAMPLES.map((example) => (
          <button key={example.question} type="button" onClick={() => fillBox(example.question)}
            className="min-h-10 rounded-full border border-line px-3 py-1 text-sm text-muted hover:border-gold/60 hover:text-text">
            {example.question}
          </button>
        ))}
      </div>

      {entries.length === 0 && status.kind === "idle" && (
        <div className="rounded-xl border border-dashed border-line p-4 text-sm text-muted">
          <p className="text-text">Ask your first question — or tap an example.</p>
          <p className="mt-1 text-xs">
            Every number marked “✓ Checked twice” was worked out in two separate ways, and both
            gave the same result.
          </p>
        </div>
      )}

      {(entries.length > 0 || status.kind !== "idle") && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs uppercase tracking-wider text-muted">
              Your questions ({entries.length})
            </h3>
            {entries.length > 0 && (
              <button type="button" onClick={clear}
                className="min-h-10 rounded px-2 text-xs text-muted hover:text-text">
                Clear
              </button>
            )}
          </div>
          <ol className="flex flex-col gap-4" aria-label="Question history, newest first">
            {status.kind !== "idle" && (
              <li ref={newest} className="flex flex-col gap-2">
                <p className="text-sm text-muted"><span className="sr-only">Question: </span>{status.question}</p>
                <PendingCard status={status} onFill={fillBox} />
              </li>
            )}
            {entries.map((entry, index) => {
              const older = index > 0 || status.kind !== "idle";
              const open = !older || expanded.has(entry.id);
              return (
                <li key={entry.id} ref={index === 0 && status.kind === "idle" ? newest : undefined}
                  className="flex flex-col gap-2">
                  {older ? (
                    <button type="button" onClick={() => toggle(entry.id)} aria-expanded={open}
                      className="min-h-9 self-start text-left text-sm text-muted hover:text-text">
                      <span className="sr-only">Question: </span>{entry.question}
                    </button>
                  ) : (
                    <p className="text-sm text-muted"><span className="sr-only">Question: </span>{entry.question}</p>
                  )}
                  <EntryCard entry={entry} onEvidence={onEvidence} onFill={fillBox}
                    coverage={coverage} collapsed={!open}
                    onToggle={older ? () => toggle(entry.id) : undefined}
                    editor={!older && entry.run?.verified ? {
                      open: editing,
                      toggle: () => setEditing(!editing),
                      chips: <PlanChips plan={entry.run.card.plan} disabled={busy} range={range}
                        onChange={(plan) => void run(plan, "")} />,
                    } : undefined} />
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </section>
  );
}

/** The newest card while it is being answered: progress, a needed choice, or a problem. */
function PendingCard({ status, onFill }: { status: Exclude<Status, { kind: "idle" }>; onFill: (text: string) => void }) {
  if (status.kind === "loading") {
    return (
      <article className="rounded-xl border border-line bg-panel p-4 sm:p-5" aria-busy="true">
        <p role="status" className="text-sm text-muted">{status.label}</p>
        <div className="mt-3 h-24 animate-pulse rounded-lg bg-raised motion-reduce:animate-none" />
      </article>
    );
  }
  if (status.kind === "clarify") {
    return <ClarificationCard plan={status.plan}
      onChoose={(option) => onFill(`${status.question} (${option})`)} />;
  }
  return <ErrorNote message={status.message} requestId={status.requestId} />;
}

function EntryCard({ entry, onEvidence, onFill, collapsed, onToggle, coverage, editor }: {
  entry: HistoryEntry;
  onEvidence: (card: Card) => void;
  onFill: (question: string) => void;
  collapsed: boolean;
  onToggle?: () => void;
  coverage: Coverage;
  editor?: { open: boolean; toggle: () => void; chips: React.ReactNode };
}) {
  if (entry.refusal) return <RefusalCard plan={entry.refusal} onAsk={onFill} />;
  const run = entry.run;
  if (!run) return null;
  // the drawer draws the same chart, so the comparison travels with the card
  const open = () => onEvidence({ ...run.card, comparison: run.comparison ?? null });
  if (!run.verified) return <UnverifiedCard answer={run} onEvidence={open} />;
  const sentence = entry.sentence ?? { status: "done", text: run.sentence, source: run.source };
  return <AnswerCard answer={run} sentence={sentence} caveats={entry.caveats} onEvidence={open}
    collapsed={collapsed} onToggle={onToggle} coverage={coverage} editor={editor} />;
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
