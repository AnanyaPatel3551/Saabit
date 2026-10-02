import { useCallback, useEffect, useState } from "react";
import { getHealth } from "../api/client";
import type { DataCheck, Dataset, Health } from "../api/types";
import { AiStatus, aiState } from "./AiStatus";
import { AskPanel } from "./AskPanel";
import { DataCheckPanel } from "./DataCheckPanel";
import { EvidenceDrawer, type EvidenceItem } from "./EvidenceDrawer";
import { InsightsPanel } from "./InsightsPanel";
import { Logo } from "./Logo";

const HEALTH_EVERY_MS = 60_000;

export function isSynthetic(dataset: Dataset): boolean {
  return dataset.filename.toLowerCase().includes("synthetic");
}

/**
 * S3: three panels, stacked on phones. Owns the health check (header status and the paused
 * banner) and the evidence drawer.
 */
export function Workspace({ dataset, check, onBack }: {
  dataset: Dataset;
  check: DataCheck;
  onBack: () => void;
}) {
  const [health, setHealth] = useState<Health | null>(null);
  const [pausedReason, setPausedReason] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<EvidenceItem[] | null>(null);

  const refresh = useCallback(() => {
    getHealth().then(setHealth).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, HEALTH_EVERY_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const llmDown = pausedReason !== null || aiState(health) === "paused";

  return (
    <div className="min-h-screen">
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-line px-4 py-3">
        <button type="button" onClick={onBack} aria-label="Saabit: start over" className="min-h-10">
          <Logo size={26} />
        </button>
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <span className="truncate text-muted">{dataset.filename}</span>
          {isSynthetic(dataset) && (
            <span className="rounded border border-line px-1.5 py-0.5 text-xs text-muted">Synthetic data</span>
          )}
          <AiStatus health={health} />
          <a href="/how-we-test" className="text-xs text-muted hover:text-text">How we test</a>
        </div>
      </header>
      <main className="grid gap-6 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_minmax(0,1.2fr)]">
        <div className="rounded-2xl border border-line bg-panel/60 p-4"><DataCheckPanel check={check} /></div>
        <div className="rounded-2xl border border-line bg-panel/60 p-4">
          <AskPanel datasetId={dataset.dataset_id} llmDown={llmDown}
            range={{ min: check.date_min ?? null, max: check.date_max ?? null }}
            partialMonths={check.partial_months}
            llmReason={pausedReason ?? health?.llm.reason ?? null}
            onLlmChange={(down, reason) => { setPausedReason(down ? reason : null); refresh(); }}
            onEvidence={(card) => setEvidence([card])} />
        </div>
        <div className="rounded-2xl border border-line bg-panel/60 p-4">
          <InsightsPanel datasetId={dataset.dataset_id} onEvidence={(ids) => setEvidence(ids)} />
        </div>
      </main>
      {evidence && <EvidenceDrawer items={evidence} onClose={() => setEvidence(null)} />}
    </div>
  );
}
