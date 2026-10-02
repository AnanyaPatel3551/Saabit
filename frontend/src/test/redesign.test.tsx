import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DataCheck, Dataset, Overview } from "../api/types";
import { DatasetChip } from "../components/DatasetChip";
import { Drawer } from "../components/Drawer";
import { PlanChips } from "../components/PlanChips";
import { ProofStrip } from "../components/ProofStrip";
import { ResultChart } from "../components/ResultChart";
import { TopStrip } from "../components/TopStrip";
import { okPlan } from "../lib/plan";

afterEach(() => vi.unstubAllGlobals());

const check: DataCheck = {
  dataset_id: "abc", rows_in: 128975, rows_out: 128975, partial_months: ["2022-03"],
  unknown_states: [], fixes: [{ rule: "state_normalised", rows_affected: 10, entries: 2 }],
  capability: { can_answer: [], cannot_answer: [] },
  date_min: "2022-03-31", date_max: "2022-06-29", orders: 120378,
};

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

  it("changing one end keeps the other at the data's bound", async () => {
    const onChange = vi.fn();
    render(<PlanChips plan={okPlan({ metric: "revenue" })} onChange={onChange}
      range={{ min: "2022-03-31", max: "2022-06-29" }} />);
    const from = screen.getByLabelText("from") as HTMLInputElement;

    fireEvent.change(from, { target: { value: "2022-05-01" } });

    expect(onChange.mock.lastCall?.[0].date_range).toEqual({ start: "2022-05-01", end: "2022-06-29" });
  });
});

describe("Order counts follow the metric", () => {
  it("says the count excludes cancelled orders for revenue", () => {
    render(<ResultChart plan={okPlan({ metric: "revenue" })} rows={[{ value: 100, orders: 103193 }]} />);
    expect(screen.getByText(/orders \(not cancelled\)/)).toBeTruthy();
  });

  it("plain orders for the cancellation rate", () => {
    render(<ResultChart plan={okPlan({ metric: "cancellation_rate" })}
      rows={[{ value: 14.2, orders: 2512 }]} />);
    expect(screen.getByText("2,512 orders")).toBeTruthy();
  });
});

const overview = {
  status: "ready", reason: null, computed_at: "now", data_check: check,
  months: { training: ["2022-04", "2022-05"], test: "2022-06" }, insights: [], rules: [],
  recommendations: [{ code: "R1", title: "Fulfilment cancellation gap", status: "fired",
    reason: null, cites: ["c1", "c2"], text: "Merchant-fulfilled orders were cancelled more often.",
    confidence: "High", confidence_reason: "High: in Jun 2022 the gap kept its sign.",
    impact: { value: 1711, formula: "36,376 orders × 4.7 ÷ 100", assumption: "a", caveat: "b" } }],
  key_numbers: [
    { metric: "revenue", label: "Revenue", value: 71673394, orders: 103193, verified: true, card_id: "k1" },
    { metric: "orders", label: "Orders", value: 120378, orders: 120378, verified: true, card_id: "k2" },
    { metric: "cancellation_rate", label: "Cancellation rate", value: 14.2759, orders: 120378, verified: true, card_id: "k3" },
    { metric: "aov", label: "Average order value", value: 694.56, orders: 103193, verified: false, card_id: "k4" },
  ],
} as unknown as Overview;

describe("Workspace top strip", () => {
  it("highlights the first recommendation with its backtest and impact", () => {
    render(<TopStrip overview={overview} onEvidence={() => undefined} />);

    expect(screen.getByText("Fulfilment cancellation gap")).toBeTruthy();
    expect(screen.getByText("Confidence: High")).toBeTruthy();
    expect(screen.getByText(/backtested on Jun 2022/)).toBeTruthy();
    expect(screen.getByText(/Estimated impact/)).toBeTruthy();
  });

  it("shows the key numbers, and no number for a tile that could not be verified", () => {
    render(<TopStrip overview={overview} onEvidence={() => undefined} />);

    expect(screen.getByText("₹7.17 Cr")).toBeTruthy();
    expect(screen.getByText("1,20,378")).toBeTruthy();
    expect(screen.getByText("14.3%")).toBeTruthy();
    expect(screen.getByText("Could not verify")).toBeTruthy();
    expect(screen.queryByText("₹694.56")).toBeNull();
  });
});

describe("Landing proof strip", () => {
  it("reads the eval summary and links to How we test", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({
      eval: { answerable: { correct: 38, total: 40 }, refused: { correct: 10, total: 10 },
              verified_but_wrong: 0, anchors_answerable: { correct: 13, total: 13 },
              anchors_refused: { correct: 2, total: 2 }, served_by: [], finished_at: "x",
              used_saved_plans: false },
      baseline: null, tests: null })));

    render(<ProofStrip />);

    expect(await screen.findByText("38/40")).toBeTruthy();
    expect(screen.getByText("pending")).toBeTruthy();  // tests not recorded yet
    expect(screen.getByRole("link").getAttribute("href")).toBe("/how-we-test");
  });
});

describe("Workspace header", () => {
  const dataset = { dataset_id: "abc", filename: "amazon_sale_report.csv.gz" } as Dataset;

  it("the dataset chip opens About this data, and Escape closes it", async () => {
    const user = userEvent.setup();
    render(<DatasetChip dataset={dataset} check={check} />);

    await user.click(screen.getByRole("button", { name: /Amazon India sales report/ }));
    expect(screen.getByRole("dialog", { name: "About this data" })).toBeTruthy();
    expect(screen.getByText(/published on Kaggle/)).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("the drawer closes on Escape", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Drawer title="Data check" onClose={onClose}><p>fixes</p></Drawer>);

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});
