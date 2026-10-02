import type { ReactNode } from "react";
import type { Overview, Recommendation } from "../api/types";
import { monthLabel } from "../lib/format";
import { VerifiedBadge } from "./VerifiedBadge";

/** "Open evidence (N cards)", or nothing when there are no cards. */
export function EvidenceLink({ ids, onEvidence }: {
  ids: string[];
  onEvidence: (cardIds: string[]) => void;
}) {
  if (ids.length === 0) return null;
  return (
    <button type="button" onClick={() => onEvidence(ids)}
      className="min-h-9 text-xs text-gold hover:underline">
      Open evidence ({ids.length} {ids.length === 1 ? "card" : "cards"})
    </button>
  );
}

/**
 * Right column: insight cards E1-E5, then the recommendations after the first (which the
 * top strip shows), then the rules that did not fire. The overview comes from the workspace.
 */
export function InsightsPanel({ overview, error, onEvidence }: {
  overview: Overview | null;
  error: string | null;
  onEvidence: (cardIds: string[]) => void;
}) {
  const more = overview?.recommendations.slice(1) ?? [];
  return (
    <section aria-labelledby="insights-heading" className="flex flex-col gap-4"
      aria-busy={overview?.status === "computing"}>
      <h2 id="insights-heading" className="font-display text-2xl text-gold-soft">Insights</h2>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      {(!overview || overview.status === "computing") && !error && (
        <p role="status" className="text-sm text-muted">Computing insight cards and checking rules…</p>
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
                    <span className="whitespace-nowrap text-xs text-muted">From the fix log</span>
                  )}
                </div>
                <p className="text-sm text-muted">
                  {insight.status === "skipped" ? `Skipped: ${insight.reason}` : insight.text}
                </p>
                {insight.status !== "skipped" && (insight.caveats ?? []).length > 0 && (
                  <ul className="mt-2 space-y-1 text-xs text-amber">
                    {insight.caveats?.map((c) => <li key={c}>Note: {c}</li>)}
                  </ul>
                )}
                <div className="mt-2"><EvidenceLink ids={insight.card_ids} onEvidence={onEvidence} /></div>
              </li>
            ))}
          </ul>

          {more.length > 0 && (
            <>
              <h2 className="mt-2 font-display text-xl text-gold-soft">More recommendations</h2>
              <ol className="flex flex-col gap-3">
                {more.map((rec, i) => (
                  <RecommendationCard key={rec.code} rank={i + 2} rec={rec}
                    evidence={<EvidenceLink ids={rec.cites} onEvidence={onEvidence} />} />
                ))}
              </ol>
            </>
          )}

          {overview.rules.some((r) => r.status !== "fired") && (
            <details className="text-sm text-muted">
              <summary className="min-h-9 cursor-pointer">Rules that did not fire</summary>
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

/** "Rules decide on Apr 2022, May 2022 and are backtested on Jun 2022." */
export function backtestLine(overview: Overview): string | null {
  const months = overview.months;
  if (!months?.test) return null;
  return `Rules decide on ${months.training.map(monthLabel).join(", ")} and are backtested on `
    + `${monthLabel(months.test)}.`;
}

export function RecommendationCard({ rank, rec, evidence, highlighted, as = "li" }: {
  rank: number;
  rec: Recommendation;
  evidence: ReactNode;
  highlighted?: boolean;
  as?: "li" | "article";
}) {
  const Tag = as;
  return (
    <Tag className={`rounded-xl border bg-panel p-4 ${highlighted ? "border-gold" : "border-gold/40"}`}>
      <div className="mb-1 flex flex-wrap items-start justify-between gap-2">
        <h3 className={`font-display text-text ${highlighted ? "text-xl" : "text-base"}`}>
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
        <p className="mt-2 text-xs text-muted">Backtest: {rec.confidence_reason}</p>
      )}
      {rec.impact && (
        <div className="mt-2 rounded-lg bg-raised p-2 text-xs">
          <p className="text-text">Estimated impact: {rec.impact.formula}</p>
          <p className="text-muted">{rec.impact.assumption}</p>
          <p className="text-muted">{rec.impact.caveat}</p>
        </div>
      )}
      <div className="mt-2">{evidence}</div>
    </Tag>
  );
}
