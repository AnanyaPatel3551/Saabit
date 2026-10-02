import type { RunOut } from "../api/types";
import { okPlan } from "../lib/plan";
import { AnswerCard } from "./AnswerCards";
import { PlanChips } from "./PlanChips";

const plan = okPlan({ metric: "cancellation_rate",
                      filters: [{ column: "state", op: "eq", values: ["Rajasthan"] }] });

/** A real answer from the sample (golden anchor: 14.2118% of 2,512 Rajasthan orders). */
const RAJASTHAN: RunOut = {
  verified: true, sentence: "Rajasthan's cancellation rate is 14.2% of 2,512 orders.",
  source: "template", sentence_status: "final", note: null,
  card: {
    card_id: "preview", dataset_id: "preview", plan, sql: "", pandas_code: "", verified: true,
    result: [{ value: 14.2118, orders: 2512 }], caveats: [], row_count: 2512,
    sql_result: null, pandas_result: null, mismatches: [], created_at: "",
  },
};

/** Static picture of an answer card, built from the real components (nothing is clickable). */
export function LandingPreview() {
  return (
    <figure className="flex flex-col gap-3" aria-label="Example answer">
      <p className="text-sm text-muted">
        <span className="sr-only">Example question: </span>rajsthan ka cancellation kitna hai
      </p>
      <div inert>
        <AnswerCard answer={RAJASTHAN} preview caveats={[]} onEvidence={() => undefined}
          sentence={{ status: "done", text: RAJASTHAN.sentence, source: "llm" }} />
      </div>
      <figcaption className="text-xs text-muted">
        Verified: SQL and pandas agree on 14.2%.
      </figcaption>
      <div inert className="opacity-90">
        <PlanChips plan={plan} preview onChange={() => undefined} />
      </div>
    </figure>
  );
}
