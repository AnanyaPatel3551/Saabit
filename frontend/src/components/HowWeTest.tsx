import { useEffect, useState } from "react";
import { getEvalSummary } from "../api/client";
import type { EvalSummary, Score } from "../api/types";
import { Logo } from "./Logo";

const PENDING = "pending";

function score(value: Score | undefined | null): string {
  return value && value.total ? `${value.correct} of ${value.total}` : PENDING;
}

/** The latest eval, the baseline and the test count, read from /api/eval-summary. */
export function HowWeTest() {
  const [summary, setSummary] = useState<EvalSummary | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getEvalSummary().then(setSummary).catch(() => setFailed(true));
  }, []);

  const run = summary?.eval ?? null;
  const base = summary?.baseline ?? null;
  const tests = summary?.tests ?? null;
  const rows: { label: string; saabit: string; baseline?: string }[] = [
    { label: "Questions answered correctly", saabit: score(run?.answerable),
      baseline: score(base?.answerable) },
    { label: "Unanswerable questions refused", saabit: score(run?.refused),
      baseline: score(base?.refused) },
    { label: "Wrong answers marked Verified", saabit: run ? String(run.verified_but_wrong) : PENDING },
    { label: "Golden anchors correct",
      saabit: run ? `${score(run.anchors_answerable)} answered, ${score(run.anchors_refused)} refused`
        : PENDING },
    { label: "Automated tests passing",
      saabit: tests ? `${tests.passed} (${tests.date})` : PENDING },
    { label: "Model and date",
      saabit: run ? `${run.served_by.join(", ") || "saved plans"} · ${run.finished_at}` : PENDING },
  ];

  const asked = run ? run.answerable.total + run.refused.total : null;
  const right = run ? run.answerable.correct + run.refused.correct : null;

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-8 px-4 py-10">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <a href="/" aria-label="Saabit home"><Logo /></a>
        <a href="/" className="text-sm text-muted hover:text-text">Back to the app</a>
      </header>

      <section aria-labelledby="test-heading" className="flex flex-col gap-3">
        <h1 id="test-heading" className="font-display text-3xl text-text">How we test</h1>
        <div data-testid="plain-summary" className="flex flex-col gap-1 text-base text-text">
          {run && asked !== null && right !== null ? (
            <>
              <p>We asked Saabit {asked} test questions about the sample file.</p>
              <p>It got {right} of {asked} right, including saying "I can't answer that" when the file could not.</p>
              <p>{run.verified_but_wrong === 0
                ? "It never showed a wrong number as checked."
                : `It showed ${run.verified_but_wrong} wrong number(s) as checked.`}</p>
            </>
          ) : (
            <p className="text-muted">The latest test results are not available yet.</p>
          )}
        </div>
      </section>

      <section aria-labelledby="judges-heading" className="flex flex-col gap-3">
        <h2 id="judges-heading" className="font-display text-2xl text-gold-soft">For judges</h2>
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
          <li>The expected answers come from a separate script in plain pandas that never uses Saabit's code.</li>
          <li>Every answer is computed twice, by SQL (DuckDB) and by pandas, and marked Verified ("Checked twice") only when both agree.</li>
          <li>"Wrong answers marked Verified" counts calculation errors: both engines agreed but the answer key disagrees.</li>
          <li>Scores come from 50 questions (10 of them should be refused) and 15 anchors, asked fresh, without saved plans.</li>
        </ul>
      </section>

      {failed && <p role="alert" className="text-sm text-bad">The results could not be loaded.</p>}

      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full text-sm">
          <caption className="sr-only">Saabit's latest eval and the baseline</caption>
          <thead className="bg-raised text-left text-muted">
            <tr>
              <th scope="col" className="px-3 py-2 font-normal">Measure</th>
              <th scope="col" className="px-3 py-2 font-normal">Saabit</th>
              <th scope="col" className="px-3 py-2 font-normal">
                Baseline{base?.product ? ` (${base.product})` : ""}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-t border-line">
                <th scope="row" className="px-3 py-2 text-left font-normal text-text">{row.label}</th>
                <td className={`px-3 py-2 tabular-nums ${row.saabit === PENDING ? "text-muted" : "text-text"}`}>
                  {row.saabit}
                </td>
                <td className="px-3 py-2 tabular-nums text-muted">{row.baseline ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {run?.used_saved_plans && (
        <p className="text-xs text-amber">Note: this run reused saved plans, so it is not a fresh score.</p>
      )}
      <p className="text-xs text-muted">
        The baseline is ChatGPT with code execution, given the same file and the same questions
        in one conversation, scored by the same rules (eval/baseline/RESULTS.md).
      </p>
    </main>
  );
}
