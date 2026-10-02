import type { KeyNumber, Overview } from "../api/types";
import { formatValue } from "../lib/format";
import { EvidenceLink, RecommendationCard, backtestLine } from "./InsightsPanel";
import { VerifiedBadge } from "./VerifiedBadge";

/**
 * Full-width strip at the top of the workspace: the first recommendation, highlighted, and
 * four whole-file totals. Every number here comes from a two-engine evidence card.
 */
export function TopStrip({ overview, onEvidence }: {
  overview: Overview | null;
  onEvidence: (cardIds: string[]) => void;
}) {
  if (!overview || overview.status !== "ready") {
    return (
      <p role="status" className="text-sm text-muted">
        {overview?.status === "failed" ? "The overview could not be computed."
          : "Computing the key numbers and checking the rules…"}
      </p>
    );
  }
  const first = overview.recommendations[0];
  const tiles = overview.key_numbers ?? [];
  const line = backtestLine(overview);
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <div className="flex flex-col gap-2">
        <h2 className="text-xs uppercase tracking-wider text-muted">Top recommendation</h2>
        {first ? (
          <RecommendationCard as="article" rank={1} rec={first} highlighted
            evidence={<EvidenceLink ids={first.cites} onEvidence={onEvidence} />} />
        ) : (
          <p className="rounded-xl border border-line bg-panel p-4 text-sm text-muted">
            No rule fired on this data, so there is no recommendation.
          </p>
        )}
        {line && <p className="text-xs text-muted">{line}</p>}
      </div>
      <div className="flex flex-col gap-2">
        <h2 className="text-xs uppercase tracking-wider text-muted">Key numbers (whole file)</h2>
        {tiles.length === 0 && <p className="text-sm text-muted">No key numbers for this file.</p>}
        <ul className="grid grid-cols-2 gap-3">
          {tiles.map((tile) => <Tile key={tile.metric} tile={tile} onEvidence={onEvidence} />)}
        </ul>
      </div>
    </div>
  );
}

function Tile({ tile, onEvidence }: { tile: KeyNumber; onEvidence: (ids: string[]) => void }) {
  return (
    <li className="flex flex-col gap-1 rounded-xl border border-line bg-panel p-3">
      <span className="text-xs text-muted">{tile.label}</span>
      {tile.verified ? (
        <span className="font-display text-2xl tabular-nums text-gold-soft">
          {formatValue(tile.metric, tile.value, true)}
        </span>
      ) : (
        <span className="text-sm text-amber">Could not verify</span>
      )}
      <span className="flex flex-wrap items-center justify-between gap-1">
        <VerifiedBadge verified={tile.verified} />
        <EvidenceLink ids={[tile.card_id]} onEvidence={onEvidence} />
      </span>
    </li>
  );
}
