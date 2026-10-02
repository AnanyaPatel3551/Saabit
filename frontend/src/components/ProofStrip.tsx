import { useEffect, useState } from "react";
import { getEvalSummary } from "../api/client";
import type { EvalSummary } from "../api/types";

/** The latest eval in four numbers, linking to /how-we-test. "pending" until produced. */
export function ProofStrip() {
  const [summary, setSummary] = useState<EvalSummary | null>(null);

  useEffect(() => {
    getEvalSummary().then(setSummary).catch(() => setSummary(null));
  }, []);

  const run = summary?.eval;
  const items = [
    { label: "questions answered correctly",
      value: run ? `${run.answerable.correct}/${run.answerable.total}` : "pending" },
    { label: "unanswerable questions refused",
      value: run ? `${run.refused.correct}/${run.refused.total}` : "pending" },
    { label: "wrong answers marked Verified", value: run ? String(run.verified_but_wrong) : "pending" },
    { label: "automated tests passing", value: summary?.tests ? String(summary.tests.passed) : "pending" },
  ];
  return (
    <a href="/how-we-test" aria-label="How we test: the latest results"
      className="group block rounded-xl border border-line bg-panel p-4 hover:border-gold/60">
      <ul className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {items.map((item) => (
          <li key={item.label} className="flex flex-col">
            <span className={`font-display text-2xl tabular-nums ${
              item.value === "pending" ? "text-muted" : "text-gold-soft"}`}>{item.value}</span>
            <span className="text-xs text-muted">{item.label}</span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-gold group-hover:underline">How we test these numbers</p>
    </a>
  );
}
