import { useState } from "react";
import type { DataCheck, Dataset } from "./api/types";
import { ConfirmColumns } from "./components/ConfirmColumns";
import { HowWeTest } from "./components/HowWeTest";
import { Landing } from "./components/Landing";
import { Privacy } from "./components/Privacy";
import { Workspace } from "./components/Workspace";

type Stage =
  | { name: "landing" }
  | { name: "confirm"; dataset: Dataset }
  | { name: "workspace"; dataset: Dataset; check: DataCheck };

/** The stage a freshly loaded dataset opens on: the sample's roles are already confirmed. */
export function stageFor(dataset: Dataset): Stage {
  return dataset.roles_confirmed && dataset.data_check
    ? { name: "workspace", dataset, check: dataset.data_check }
    : { name: "confirm", dataset };
}

/**
 * One page app with three stages: landing (S1), confirm columns (S2), workspace (S3). The
 * other pages, /how-we-test and /privacy, are picked by the URL (no router library).
 */
export default function App() {
  const [stage, setStage] = useState<Stage>({ name: "landing" });
  const restart = () => setStage({ name: "landing" });

  if (window.location.pathname === "/how-we-test") return <HowWeTest />;
  if (window.location.pathname === "/privacy") return <Privacy />;
  if (stage.name === "landing") {
    return <Landing onDataset={(dataset) => setStage(stageFor(dataset))} />;
  }
  if (stage.name === "confirm") {
    return (
      <ConfirmColumns dataset={stage.dataset} onBack={restart}
        onConfirmed={(check) => setStage({ name: "workspace", dataset: stage.dataset, check })} />
    );
  }
  return <Workspace key={stage.dataset.dataset_id} dataset={stage.dataset} check={stage.check}
    onBack={restart} />;
}
