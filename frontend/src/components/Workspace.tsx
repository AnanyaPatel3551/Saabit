import { useCallback, useEffect, useState } from "react";
import { deleteDataset, getHealth } from "../api/client";
import { clearHistory } from "../lib/history";
import type { DataCheck, Dataset, Health } from "../api/types";
import { AiStatus, aiState } from "./AiStatus";
import { AskPanel } from "./AskPanel";
import { DataCheckPanel } from "./DataCheckPanel";
import { EvidenceDrawer, type EvidenceItem } from "./EvidenceDrawer";
import { InsightsPanel } from "./InsightsPanel";
import { Logo } from "./Logo";

const HEALTH_EVERY_MS = 60_000;

const SAMPLE_FILE = "amazon_sale_report.csv.gz";  // the shared sample, which cannot be deleted

export function isSharedSample(dataset: Dataset): boolean {
  return dataset.filename === SAMPLE_FILE;
}

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
          <a href="/privacy" className="text-xs text-muted hover:text-text">Privacy</a>
          {!isSharedSample(dataset) && <DeleteMyData datasetId={dataset.dataset_id} onDeleted={onBack} />}
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

/** "Delete my data now": deletes this upload on the server and its history in this browser. */
function DeleteMyData({ datasetId, onDeleted }: { datasetId: string; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await deleteDataset(datasetId);
      clearHistory(datasetId);
      onDeleted();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  if (!confirming) {
    return (
      <button type="button" onClick={() => setConfirming(true)}
        className="min-h-10 rounded border border-line px-2 text-xs text-muted hover:border-bad/60 hover:text-text">
        Delete my data now
      </button>
    );
  }
  return (
    <span role="group" aria-label="Confirm deleting your data" className="inline-flex flex-wrap items-center gap-2 text-xs">
      <span className="text-text">Delete this file and its answers from the server?</span>
      <button type="button" onClick={() => void remove()} disabled={busy}
        className="min-h-10 rounded border border-bad/70 px-2 text-text hover:bg-bad/10 disabled:opacity-50">
        {busy ? "Deleting…" : "Yes, delete"}
      </button>
      <button type="button" onClick={() => setConfirming(false)} disabled={busy}
        className="min-h-10 px-2 text-muted hover:text-text">
        Cancel
      </button>
      {error && <span role="alert" className="text-bad">{error}</span>}
    </span>
  );
}
