import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Card, RunOut } from "../api/types";
import { AnswerCard } from "../components/AnswerCards";
import { EvidenceDrawer } from "../components/EvidenceDrawer";
import { okPlan } from "../lib/plan";

const TECHNICAL = /\b(SQL|pandas|DuckDB|plan|JSON|LLM|Groq|NIM|NVIDIA)\b/i;
const plan = okPlan({ metric: "revenue", group_by: ["month"] });
const card: Card = {
  card_id: "abc-1", dataset_id: "abc", plan, sql: "SELECT 1", pandas_code: "df.sum()",
  verified: true, result: [{ month: "2022-04", value: 100, orders: 2 }], caveats: [],
  row_count: 2, sql_result: null, pandas_result: null, mismatches: [], created_at: "now",
};
const run: RunOut = { verified: true, sentence: "Revenue in Apr 2022 was ₹100.", source: "template",
  sentence_status: "final", note: null, card,
  explanation: ["Revenue: money from orders that were not cancelled."] };

afterEach(() => vi.unstubAllGlobals());

describe("Plain language", () => {
  it("an answer card uses no technical words", () => {
    const { container } = render(<AnswerCard answer={run} caveats={[]} onEvidence={() => undefined}
      sentence={{ status: "done", text: run.sentence, source: "llm" }} />);

    expect(container.textContent).not.toMatch(TECHNICAL);
  });

  it("the evidence drawer keeps technical words inside Technical details only", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ rows: [], page: 1, pages: 1, total: 0 })));
    render(<EvidenceDrawer items={[card]} onClose={() => undefined} />);

    for (const tab of ["Chart", "What we counted", "Rows", "Good to know"]) {
      await user.click(screen.getByRole("tab", { name: tab }));
      expect(screen.getByRole("tabpanel").textContent).not.toMatch(TECHNICAL);
    }
    await user.click(screen.getByRole("tab", { name: /Technical details/ }));
    expect(screen.getByRole("tabpanel").textContent).toMatch(/SQL/);
  });
});
