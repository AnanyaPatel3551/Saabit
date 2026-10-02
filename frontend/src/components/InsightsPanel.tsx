import { useEffect, useState, type ReactNode } from "react";
import { getOverview } from "../api/client";
import type { Overview, Recommendation } from "../api/types";
import { monthLabel } from "../lib/format";
import { VerifiedBadge } from "./VerifiedBadge";

const POLL_MS = 2000;

/** Right panel: insight cards E1-E5 and ranked recommendations from /overview (FR-8). */
export function InsightsPanel({ datasetId, onEvidence, onCount }: {
  datasetId: string;
  onEvidence: (cardIds: string[]) => void;
  /** How many insight cards have something to show, once they are ready. */
  onCount?: (count: number) => void;
}) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const next = await getOverview(datasetId);
        if (!live) return;
        setOverview(next);
        if (next.status === "ready") onCount?.(next.insights.filter((i) => i.status !== "skipped").length);
        if (next.status === "computing") timer = setTimeout(poll, POLL_MS);
      } catch (e) {
        if (live) setError((e as Error).message);
      }
    };
    void poll();
    return () => { live = false; clearTimeout(timer); };
  }, [datasetId]);  // eslint-disable-line react-hooks/exhaustive-deps

  const evidenceButton = (ids: string[]) => ids.length > 0 && (
    <button type="button" onClick={() => onEvidence(ids)} className="text-xs text-gold hover:underline">
      See how we got this ({ids.length} {ids.length === 1 ? "answer" : "answers"})
    </button>
  );

  return (
    <section aria-labelledby="insights-heading" className="flex flex-col gap-4" aria-busy={overview?.status === "computing"}>
      <h2 id="insights-heading" className="font-display text-2xl text-gold-soft">Insights</h2>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      {(!overview || overview.status === "computing") && !error && (
        <p role="status" className="text-sm text-muted">Working out the insights…</p>
      )}
      {overview?.status === "failed" && (
        <p role="alert" className="text-sm text-bad">Insights could not be computed: {overview.reason}</p>
      )}

      {overview?.status === "ready" && (
        <>
          <ul className="flex flex-col gap-3">
            {overview.insights.map((insight) => (
              <li key={insight.code} className="rounded-xl border border-line bg-panel p-4">
                <div className="mb-1 flex items-start justify-between gap-2">
                  <h3 className="font-display text-base text-text">{insight.title}</h3>
                  {/* Verified only where SQL and pandas both computed the card */}
                  {insight.status !== "skipped" && insight.source === "engines"
                    && <VerifiedBadge verified={insight.verified} />}
                  {insight.source === "fix_log" && (
                    <span className="whitespace-nowrap text-xs text-muted">From our data clean-up</span>
                  )}
                </div>
                <p className="text-sm text-muted">
                  {insight.status === "skipped" ? `Skipped: ${insight.reason}` : insight.text}
                </p>
                {insight.status !== "skipped" && (insight.caveats ?? []).length > 0 && (
                  <ul className="mt-2 space-y-1 text-xs text-amber">
                    {insight.caveats?.map((c) => <li key={c}>Good to know: {c}</li>)}
                  </ul>
                )}
                <div className="mt-2">{evidenceButton(insight.card_ids)}</div>
              </li>
            ))}
          </ul>

          <h2 className="mt-2 font-display text-2xl text-gold-soft">Recommendations</h2>
          {overview.months?.test && (
            <p className="text-xs text-muted">
              Rules decide on {overview.months.training.map(monthLabel).join(", ")} and are
              backtested on {monthLabel(overview.months.test)}.
            </p>
          )}
          {overview.recommendations.length === 0 && (
            <p className="text-sm text-muted">No rule fired on this data.</p>
          )}
          <ol className="flex flex-col gap-3">
            {overview.recommendations.map((rec, i) => (
              <RecommendationCard key={rec.code} rank={i + 1} rec={rec} evidence={evidenceButton(rec.cites)} />
            ))}
          </ol>

          {overview.rules.some((r) => r.status !== "fired") && (
            <details className="text-sm text-muted">
              <summary className="cursor-pointer">Rules that did not fire</summary>
              <ul className="mt-2 space-y-1">
                {overview.rules.filter((r) => r.status !== "fired").map((r) => (
                  <li key={r.code}><span className="text-text">{r.title}:</span> {r.reason}</li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}

function RecommendationCard({ rank, rec, evidence }: {
  rank: number;
  rec: Recommendation;
  evidence: ReactNode;
}) {
  return (
    <li className="rounded-xl border border-gold/40 bg-panel p-4">
      <div className="mb-1 flex items-start justify-between gap-2">
        <h3 className="font-display text-base text-text">
          <span className="text-gold">{rank}.</span> {rec.title}
        </h3>
        {rec.confidence && (
          <span className="whitespace-nowrap rounded-full border border-line px-2 py-0.5 text-xs text-text"
            title={rec.confidence_reason}>
            Confidence: {rec.confidence}
          </span>
        )}
      </div>
      <p className="text-sm text-muted">{rec.text}</p>
      {rec.confidence_reason && (
        <p className="mt-2 text-xs text-muted">Why this confidence: {rec.confidence_reason}</p>
      )}
      {rec.impact && (
        <div className="mt-2 rounded-lg bg-raised p-2 text-xs">
          <p className="text-text">Estimated impact: {rec.impact.formula}</p>
          <p className="text-muted">{rec.impact.assumption}</p>
          <p className="text-muted">{rec.impact.caveat}</p>
        </div>
      )}
      <div className="mt-2">{evidence}</div>
    </li>
  );
}
