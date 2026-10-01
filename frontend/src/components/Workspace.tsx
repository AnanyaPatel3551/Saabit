import { useEffect, useState } from "react";
import { getHealth } from "../api/client";
import type { DataCheck, Dataset } from "../api/types";
import { AskPanel } from "./AskPanel";
import { DataCheckPanel } from "./DataCheckPanel";
import { EvidenceDrawer, type EvidenceItem } from "./EvidenceDrawer";
import { InsightsPanel } from "./InsightsPanel";

const DOWN = new Set(["unavailable", "not_configured"]);

/** S3: three panels, stacked on phones. Owns the health check and the evidence drawer. */
export function Workspace({ dataset, check, onBack }: {
  dataset: Dataset;
  check: DataCheck;
  onBack: () => void;
}) {
  const [llm, setLlm] = useState<{ down: boolean; reason: string | null }>({ down: false, reason: null });
  const [evidence, setEvidence] = useState<EvidenceItem[] | null>(null);

  useEffect(() => {
    getHealth()
      .then((h) => setLlm({ down: DOWN.has(h.llm.status), reason: h.llm.reason }))
      .catch(() => undefined);
  }, []);

  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between border-b border-line px-4 py-3">
        <button type="button" onClick={onBack} className="font-display text-xl text-gold">Saabit</button>
        <span className="truncate text-sm text-muted">{dataset.filename}</span>
      </header>
      <main className="grid gap-6 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_minmax(0,1.2fr)]">
        <div className="rounded-2xl border border-line bg-panel/60 p-4"><DataCheckPanel check={check} /></div>
        <div className="rounded-2xl border border-line bg-panel/60 p-4">
          <AskPanel datasetId={dataset.dataset_id} llmDown={llm.down} llmReason={llm.reason}
            onLlmChange={(down, reason) => setLlm({ down, reason })}
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
