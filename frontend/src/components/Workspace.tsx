import { useCallback, useEffect, useState, type KeyboardEvent } from "react";
import { deleteDataset, getHealth } from "../api/client";
import { monthCoverage } from "../lib/coverage";
import { clearHistory } from "../lib/history";
import type { DataCheck, Dataset, Health } from "../api/types";
import { AiStatus, aiState } from "./AiStatus";
import { AskPanel } from "./AskPanel";
import { DataCheckPanel } from "./DataCheckPanel";
import { EvidenceDrawer, type EvidenceItem } from "./EvidenceDrawer";
import { InsightsPanel } from "./InsightsPanel";
import { Logo } from "./Logo";

const HEALTH_EVERY_MS = 60_000;

export const TABS = ["Ask", "Insights", "Your data"] as const;
export type WorkspaceTab = (typeof TABS)[number];
const TAB_KEY = "saabit:tab";

function savedTab(): WorkspaceTab {
  try {
    const saved = localStorage.getItem(TAB_KEY);
    return (TABS as readonly string[]).includes(saved ?? "") ? (saved as WorkspaceTab) : "Ask";
  } catch {
    return "Ask";
  }
}

function rememberTab(tab: WorkspaceTab): void {
  try {
    localStorage.setItem(TAB_KEY, tab);
  } catch {
    // the tab simply resets to Ask next time
  }
}

const tabId = (tab: WorkspaceTab) => `ws-tab-${tab.replace(/ /g, "-")}`;

const SAMPLE_FILE = "amazon_sale_report.csv.gz";  // the shared sample, which cannot be deleted

export function isSharedSample(dataset: Dataset): boolean {
  return dataset.filename === SAMPLE_FILE;
}

export function isSynthetic(dataset: Dataset): boolean {
  return dataset.filename.toLowerCase().includes("synthetic");
}

/**
 * S3: three tabs under the header (Ask, Insights, Your data), one at a time, content at most
 * 900px wide. Every panel stays mounted while hidden, so switching tabs keeps its state. Owns
 * the health check (header status and the paused banner) and the evidence drawer, which
 * answers and insight cards share.
 */
export function Workspace({ dataset, check, onBack }: {
  dataset: Dataset;
  check: DataCheck;
  onBack: () => void;
}) {
  const [health, setHealth] = useState<Health | null>(null);
  const [pausedReason, setPausedReason] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<EvidenceItem[] | null>(null);
  const [tab, setTab] = useState<WorkspaceTab>(savedTab);
  const [insightCount, setInsightCount] = useState<number | null>(null);

  function choose(next: WorkspaceTab) {
    setTab(next);
    rememberTab(next);
  }

  function onTabKey(event: KeyboardEvent) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    const jump = event.key === "Home" ? TABS[0] : event.key === "End" ? TABS[TABS.length - 1] : null;
    if (!step && !jump) return;
    event.preventDefault();
    const next = jump ?? TABS[(TABS.indexOf(tab) + step + TABS.length) % TABS.length];
    choose(next);
    document.getElementById(tabId(next))?.focus();
  }

  const refresh = useCallback(() => {
    getHealth().then(setHealth).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, HEALTH_EVERY_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const llmDown = pausedReason !== null || aiState(health) === "paused";
  const coverage = monthCoverage(check.date_min, check.date_max);

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
      <div className="border-b border-line">
        <div role="tablist" aria-label="Workspace" className="mx-auto flex max-w-[900px] gap-1 overflow-x-auto px-4">
          {TABS.map((t) => (
            <button key={t} id={tabId(t)} role="tab" type="button" aria-selected={tab === t}
              aria-controls={`${tabId(t)}-panel`} tabIndex={tab === t ? 0 : -1}
              onClick={() => choose(t)} onKeyDown={onTabKey}
              className={`min-h-11 whitespace-nowrap border-b-2 px-4 py-2 text-sm ${tab === t
                ? "border-gold text-text" : "border-transparent text-muted hover:text-text"}`}>
              {t}
              {t === "Insights" && insightCount !== null && (
                <span className="ml-1.5 rounded-full bg-raised px-1.5 py-0.5 text-xs tabular-nums text-muted">
                  {insightCount}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>
      <main className="mx-auto w-full max-w-[900px] p-4">
        <div id={`${tabId("Ask")}-panel`} role="tabpanel" aria-labelledby={tabId("Ask")} hidden={tab !== "Ask"}>
          <AskPanel datasetId={dataset.dataset_id} llmDown={llmDown}
            range={{ min: check.date_min ?? null, max: check.date_max ?? null }}
            coverage={coverage}
            llmReason={pausedReason ?? health?.llm.reason ?? null}
            onLlmChange={(down, reason) => { setPausedReason(down ? reason : null); refresh(); }}
            onEvidence={(card) => setEvidence([card])} />
        </div>
        <div id={`${tabId("Insights")}-panel`} role="tabpanel" aria-labelledby={tabId("Insights")}
          hidden={tab !== "Insights"}>
          <InsightsPanel datasetId={dataset.dataset_id} onEvidence={(ids) => setEvidence(ids)}
            onCount={setInsightCount} />
        </div>
        <div id={`${tabId("Your data")}-panel`} role="tabpanel" aria-labelledby={tabId("Your data")}
          hidden={tab !== "Your data"}>
          <DataCheckPanel check={check} />
        </div>
      </main>
      {evidence && <EvidenceDrawer items={evidence} coverage={coverage} onClose={() => setEvidence(null)} />}
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
