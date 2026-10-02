import { useCallback, useEffect, useState } from "react";
import { getHealth } from "../api/client";
import type { DataCheck, Dataset, Health } from "../api/types";
import { useOverview } from "../lib/useOverview";
import { AiStatus, aiState } from "./AiStatus";
import { AskPanel } from "./AskPanel";
import { DataCheckPanel } from "./DataCheckPanel";
import { DatasetChip } from "./DatasetChip";
import { Drawer } from "./Drawer";
import { EvidenceDrawer, type EvidenceItem } from "./EvidenceDrawer";
import { InsightsPanel } from "./InsightsPanel";
import { Logo } from "./Logo";
import { TopStrip } from "./TopStrip";

export { isSynthetic } from "./DatasetChip";

const HEALTH_EVERY_MS = 60_000;

/**
 * S3. Header (dataset, data check, AI status), a full-width strip with the top
 * recommendation and key numbers, then Ask with its thread beside the insight cards.
 * Everything stacks on phones.
 */
export function Workspace({ dataset, check, onBack }: {
  dataset: Dataset;
  check: DataCheck;
  onBack: () => void;
}) {
  const [health, setHealth] = useState<Health | null>(null);
  const [pausedReason, setPausedReason] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<EvidenceItem[] | null>(null);
  const [showCheck, setShowCheck] = useState(false);
  const { overview, error } = useOverview(dataset.dataset_id);

  const refresh = useCallback(() => {
    getHealth().then(setHealth).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, HEALTH_EVERY_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const llmDown = pausedReason !== null || aiState(health) === "paused";
  const fixCount = check.fixes.length;

  return (
    <div className="min-h-screen">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-4 py-3">
        <button type="button" onClick={onBack} aria-label="Saabit: start over" className="min-h-10">
          <Logo size={26} />
        </button>
        <DatasetChip dataset={dataset} check={check} />
        <button type="button" onClick={() => setShowCheck(true)}
          className="min-h-10 rounded-full border border-line px-3 text-xs text-text hover:border-gold/60">
          Data check <span className="text-muted">· {fixCount} {fixCount === 1 ? "fix" : "fixes"}</span>
        </button>
        <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1">
          <AiStatus health={health} />
          <a href="/how-we-test" className="text-xs text-muted hover:text-text">How we test</a>
        </div>
      </header>

      <main className="flex flex-col gap-6 p-4">
        <section aria-label="Overview" className="rounded-2xl border border-line bg-panel/60 p-4">
          <TopStrip overview={overview} onEvidence={(ids) => setEvidence(ids)} />
        </section>
        <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div className="rounded-2xl border border-line bg-panel/60 p-4">
            <AskPanel datasetId={dataset.dataset_id} llmDown={llmDown}
              range={{ min: check.date_min ?? null, max: check.date_max ?? null }}
              llmReason={pausedReason ?? health?.llm.reason ?? null}
              onLlmChange={(down, reason) => { setPausedReason(down ? reason : null); refresh(); }}
              onEvidence={(card) => setEvidence([card])} />
          </div>
          <div className="rounded-2xl border border-line bg-panel/60 p-4">
            <InsightsPanel overview={overview} error={error} onEvidence={(ids) => setEvidence(ids)} />
          </div>
        </div>
      </main>

      {showCheck && (
        <Drawer title="Data check" onClose={() => setShowCheck(false)}>
          <DataCheckPanel check={check} />
        </Drawer>
      )}
      {evidence && <EvidenceDrawer items={evidence} onClose={() => setEvidence(null)} />}
    </div>
  );
}
