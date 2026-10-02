import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PlanChips } from "../components/PlanChips";
import type { Plan, ResultRow, RunOut } from "../api/types";
import { AnswerCard, UnverifiedCard } from "../components/AnswerCards";
import { TypingHeadline } from "../components/TypingHeadline";
import { okPlan } from "../lib/plan";

describe("Plan chips", () => {
  it("shows no empty filter row until + filter is clicked", async () => {
    const user = userEvent.setup();
    render(<PlanChips plan={okPlan({ metric: "revenue" })} onChange={() => undefined} />);

    expect(screen.queryByLabelText("Filter value")).toBeNull();
    await user.click(screen.getByRole("button", { name: "+ filter" }));
    expect(screen.getByLabelText("Filter value")).toBeTruthy();
  });

  it("fills the date fields with the data's real range", () => {
    render(<PlanChips plan={okPlan({ metric: "revenue" })} onChange={() => undefined}
      range={{ min: "2022-03-31", max: "2022-06-29" }} />);

    expect((screen.getByLabelText("from") as HTMLInputElement).value).toBe("2022-03-31");
    expect((screen.getByLabelText("to") as HTMLInputElement).value).toBe("2022-06-29");
  });

  it("changing one end keeps the other at the data's bound", () => {
    const onChange = vi.fn();
    render(<PlanChips plan={okPlan({ metric: "revenue" })} onChange={onChange}
      range={{ min: "2022-03-31", max: "2022-06-29" }} />);

    fireEvent.change(screen.getByLabelText("from"), { target: { value: "2022-05-01" } });

    expect(onChange.mock.lastCall?.[0].date_range).toEqual({ start: "2022-05-01", end: "2022-06-29" });
  });
});

const runFor = (plan: Plan, result: ResultRow[], extra: Partial<RunOut> = {}): RunOut => ({
  verified: true, sentence: "Answer.", source: "template", sentence_status: "final", note: null,
  card: { card_id: "abc-1", dataset_id: "abc", plan, sql: "", pandas_code: "", verified: true,
          result, caveats: [], row_count: 2650, sql_result: null, pandas_result: null,
          mismatches: [], created_at: "" },
  ...extra,
});
const done = { status: "done" as const, text: "Answer.", source: "llm" };

describe("Answer card evidence", () => {
  const rajasthan = okPlan({ metric: "cancellation_rate",
                             filters: [{ column: "state", op: "eq", values: ["Rajasthan"] }] });

  it("shows a proof line on a verified answer", () => {
    render(<AnswerCard answer={runFor(rajasthan, [{ value: 14.2118, orders: 2512 }])}
      sentence={done} caveats={[]} onEvidence={() => undefined} />);

    expect(screen.getByTestId("proof-line").textContent).toContain("SQL and pandas both gave 14.2%");
  });

  it("shows a proof line with both values when the engines disagree", () => {
    const run = runFor(okPlan({ metric: "revenue" }), [], { verified: false, source: "unverified",
      note: "Could not verify this answer: the two calculation engines disagree. SQL: ₹2,39,53,534. pandas: ₹2,41,93,069." });

    render(<UnverifiedCard answer={run} onEvidence={() => undefined} />);

    expect(screen.getByTestId("proof-line").textContent).toContain("SQL gave ₹2,39,53,534; pandas gave ₹2,41,93,069");
  });

  it("draws no chart for a single number with nothing to compare", () => {
    render(<AnswerCard answer={runFor(okPlan({ metric: "orders" }), [{ value: 120378, orders: 120378 }])}
      sentence={done} caveats={[]} onEvidence={() => undefined} />);

    expect(screen.queryByTestId("evidence-chart")).toBeNull();
    expect(screen.getByText("1,20,378")).toBeTruthy();
  });

  it("compares a filtered single number with all orders", () => {
    const run = runFor(rajasthan, [{ value: 14.2118, orders: 2512 }],
      { comparison: { label: "all orders", value: 14.2759, verified: true, card_id: "abc-2" } });

    render(<AnswerCard answer={run} sentence={done} caveats={[]} onEvidence={() => undefined} />);

    const chart = screen.getByTestId("evidence-chart");
    expect(chart.textContent).toContain("Rajasthan");
    expect(chart.textContent).toContain("all orders");
    expect(chart.textContent).toContain("14.3%");
  });

  it("explains the calculation and shows the first source rows with a download link", () => {
    const run = runFor(rajasthan, [{ value: 14.2118, orders: 2512 }], {
      explanation: ["Cancellation rate: Distinct cancelled orders divided by distinct orders, times 100."],
      rows_preview: [{ order_id: "171-1", state: "Rajasthan" }, { order_id: "171-2", state: "Rajasthan" }],
    });

    render(<AnswerCard answer={run} sentence={done} caveats={[]} onEvidence={() => undefined} />);

    expect(screen.getByText(/Distinct cancelled orders divided by distinct orders/)).toBeTruthy();
    expect(screen.getByText("171-2")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Download all 2,650 rows (CSV)" })).toBeTruthy();
  });

  it("a collapsed older answer keeps the sentence, number and proof line only", () => {
    render(<AnswerCard answer={runFor(rajasthan, [{ value: 14.2118, orders: 2512 }],
      { explanation: ["Period: every date in the file."] })}
      sentence={done} caveats={[]} onEvidence={() => undefined} collapsed onToggle={() => undefined} />);

    expect(screen.getByTestId("proof-line")).toBeTruthy();
    expect(screen.queryByText("Period: every date in the file.")).toBeNull();
    expect(screen.getByRole("button", { name: "Show the evidence" })).toBeTruthy();
  });
});

describe("Order counts follow the metric", () => {
  it("says non-cancelled orders for revenue", () => {
    render(<AnswerCard answer={runFor(okPlan({ metric: "revenue" }), [{ value: 100, orders: 103193 }])}
      sentence={done} caveats={[]} onEvidence={() => undefined} />);
    expect(screen.getByText(/1,03,193 non-cancelled orders/)).toBeTruthy();
  });

  it("plain orders for the cancellation rate", () => {
    render(<AnswerCard answer={runFor(okPlan({ metric: "cancellation_rate" }), [{ value: 14.2, orders: 2512 }])}
      sentence={done} caveats={[]} onEvidence={() => undefined} />);
    expect(screen.getByText("2,512 orders")).toBeTruthy();
  });
});

describe("Landing headline", () => {
  it("shows the full headline at once when reduced motion is set", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"),
      media: query, addEventListener() {}, removeEventListener() {} }));

    render(<TypingHeadline first="Ask your sales data anything." second="Every number checked twice." />);

    const heading = screen.getByRole("heading");
    expect(heading.getAttribute("aria-label")).toBe("Ask your sales data anything. Every number checked twice.");
    expect(heading.textContent).toContain("Every number checked twice.Every number checked twice.");
    expect(document.querySelector(".typing-caret")).toBeNull();
    vi.unstubAllGlobals();
  });
});
