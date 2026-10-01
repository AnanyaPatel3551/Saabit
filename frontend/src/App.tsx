import { useState } from "react";
import type { DataCheck, Dataset } from "./api/types";
import { ConfirmColumns } from "./components/ConfirmColumns";
import { Landing } from "./components/Landing";
import { Workspace } from "./components/Workspace";

type Stage =
  | { name: "landing" }
  | { name: "confirm"; dataset: Dataset }
  | { name: "workspace"; dataset: Dataset; check: DataCheck };

/** One page, three stages: landing (S1), confirm columns (S2), workspace (S3). */
export default function App() {
  const [stage, setStage] = useState<Stage>({ name: "landing" });
  const restart = () => setStage({ name: "landing" });

  if (stage.name === "landing") {
    return <Landing onDataset={(dataset) => setStage({ name: "confirm", dataset })} />;
  }
  if (stage.name === "confirm") {
    return (
      <ConfirmColumns dataset={stage.dataset} onBack={restart}
        onConfirmed={(check) => setStage({ name: "workspace", dataset: stage.dataset, check })} />
    );
  }
  return <Workspace dataset={stage.dataset} check={stage.check} onBack={restart} />;
}
