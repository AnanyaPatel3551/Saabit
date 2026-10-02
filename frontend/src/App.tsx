import { useEffect, useState } from "react";
import { getDataset } from "./api/client";
import type { DataCheck, Dataset } from "./api/types";
import { ConfirmColumns } from "./components/ConfirmColumns";
import { friendlyError } from "./components/ErrorNote";
import { HowWeTest } from "./components/HowWeTest";
import { Landing } from "./components/Landing";
import { Privacy } from "./components/Privacy";
import { Workspace, isSharedSample } from "./components/Workspace";
import { keyFor } from "./lib/datasetKeys";
import { clearActive, loadActive, saveActive, type ActiveDataset } from "./lib/session";

type Stage =
  | { name: "landing"; notice?: string }
  | { name: "restoring"; active: ActiveDataset }
  | { name: "confirm"; dataset: Dataset }
  | { name: "workspace"; dataset: Dataset; check: DataCheck };

export const OTHER_TAB_MESSAGE =
  "For privacy, an upload opens only in the browser tab that uploaded it. Please upload it again.";

/** The stage a freshly loaded dataset opens on: the sample's roles are already confirmed. */
export function stageFor(dataset: Dataset): Stage {
  return dataset.roles_confirmed && dataset.data_check
    ? { name: "workspace", dataset, check: dataset.data_check }
    : { name: "confirm", dataset };
}

function initialStage(): Stage {
  const active = loadActive();
  if (!active) return { name: "landing" };
  if (!active.sample && !keyFor(active.id)) {
    clearActive();
    return { name: "landing", notice: OTHER_TAB_MESSAGE };
  }
  return { name: "restoring", active };
}

/**
 * One page app with three stages: landing (S1), confirm columns (S2), workspace (S3). The
 * other pages, /how-we-test and /privacy, are picked by the URL (no router library). The open
 * dataset is remembered, so a refresh reopens it with its question history.
 */
export default function App() {
  const [stage, setStage] = useState<Stage>(initialStage);
  const restart = () => {
    clearActive();
    setStage({ name: "landing" });
  };
  const open = (dataset: Dataset) => {
    saveActive({ id: dataset.dataset_id, sample: isSharedSample(dataset) });
    setStage(stageFor(dataset));
  };

  useEffect(() => {
    if (stage.name !== "restoring") return;
    let live = true;
    getDataset(stage.active.id)
      .then((dataset) => live && setStage(stageFor(dataset)))
      .catch((error: unknown) => {
        if (!live) return;
        clearActive();
        setStage({ name: "landing", notice: friendlyError(error).message });
      });
    return () => { live = false; };
  }, [stage]);

  if (window.location.pathname === "/how-we-test") return <HowWeTest />;
  if (window.location.pathname === "/privacy") return <Privacy />;
  if (stage.name === "restoring") {
    return <main className="mx-auto max-w-3xl px-4 py-12 text-sm text-muted" role="status">Opening your file…</main>;
  }
  if (stage.name === "landing") return <Landing notice={stage.notice} onDataset={open} />;
  if (stage.name === "confirm") {
    return (
      <ConfirmColumns dataset={stage.dataset} onBack={restart}
        onConfirmed={(check) => setStage({ name: "workspace", dataset: stage.dataset, check })} />
    );
  }
  return <Workspace key={stage.dataset.dataset_id} dataset={stage.dataset} check={stage.check}
    onBack={restart} />;
}
