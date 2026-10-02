import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DataCheck, Dataset } from "../api/types";
import { AskPanel, withMonth } from "../components/AskPanel";
import { Workspace } from "../components/Workspace";
import { monthCoverage } from "../lib/coverage";

const check: DataCheck = {
  dataset_id: "sample000000", rows_in: 128975, rows_out: 128975, partial_months: ["2022-03"],
  unknown_states: [], fixes: [], capability: { can_answer: [{ topic: "revenue", reason: "" }], cannot_answer: [] },
  date_min: "2022-03-31", date_max: "2022-06-29",
};
const dataset = { dataset_id: "sample000000", filename: "amazon_sale_report.csv.gz", size_bytes: 1,
  rows: 1, created_at: "", columns: [], roles: [], roles_confirmed: true, missing_required: [],
  unmapped_columns: [], data_check: check } as Dataset;
const insight = { status: "ok", reason: null, card_ids: ["sample000000-0a1b2c3d"], verified: true,
  caveats: [], source: "engines" };

function backend(calls: string[] = []) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    if (url.includes("/overview")) {
      return Response.json({ status: "ready", reason: null, computed_at: "now", months: null,
        data_check: check, recommendations: [], rules: [], insights: [
          { ...insight, code: "E2", title: "Monthly revenue trend", text: "Revenue by month." },
          { ...insight, code: "E3", title: "Top 10 states by orders", text: "Maharashtra leads." },
          { ...insight, code: "E4", title: "Skipped one", status: "skipped", text: null, reason: "no column" },
        ] });
    }
    return Response.json({ status: "ok", version: "x", llm: { provider: "groq", model: "m",
      status: "unknown", reason: null, checked_at: null, state: "unknown", providers: [] } });
  }));
  return calls;
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("Workspace tabs", () => {
  it("opens on Ask, switches tabs, and remembers the choice", async () => {
    const user = userEvent.setup();
    backend();
    const first = render(<Workspace dataset={dataset} check={check} onBack={() => undefined} />);

    expect(screen.getByRole("tab", { name: "Ask" }).getAttribute("aria-selected")).toBe("true");
    await user.click(screen.getByRole("tab", { name: /Your data/ }));
    expect(screen.getByRole("tabpanel").textContent).toContain("Can answer");
    first.unmount();

    render(<Workspace dataset={dataset} check={check} onBack={() => undefined} />);
    expect(screen.getByRole("tab", { name: /Your data/ }).getAttribute("aria-selected")).toBe("true");
  });

  it("moves between tabs with the arrow keys", async () => {
    const user = userEvent.setup();
    backend();
    render(<Workspace dataset={dataset} check={check} onBack={() => undefined} />);

    screen.getByRole("tab", { name: "Ask" }).focus();
    await user.keyboard("{ArrowRight}");

    expect(document.activeElement?.textContent).toMatch(/^Insights/);
    expect(screen.getByRole("tab", { name: /Insights/ }).getAttribute("aria-selected")).toBe("true");
  });

  it("shows how many insights there are on the Insights tab", async () => {
    backend();
    render(<Workspace dataset={dataset} check={check} onBack={() => undefined} />);

    const tab = screen.getByRole("tab", { name: /Insights/ });
    expect(await within(tab).findByText("2")).toBeTruthy();
  });
});

describe("Month chips", () => {
  it("adds, replaces and removes the month phrase", () => {
    expect(withMonth("orders by state", "May 2022")).toBe("orders by state in May 2022");
    expect(withMonth("orders by state in May 2022", "Jun 2022")).toBe("orders by state in Jun 2022");
    expect(withMonth("orders by state in May 2022", null)).toBe("orders by state");
    expect(withMonth("", "Apr 2022")).toBe("in Apr 2022");
  });

  it("show every month with partial hints, fill the box and never send", async () => {
    const user = userEvent.setup();
    const calls = backend();
    render(<AskPanel datasetId="sample000000" llmDown={false} llmReason={null}
      coverage={monthCoverage("2022-03-31", "2022-06-29")}
      onLlmChange={() => undefined} onEvidence={() => undefined} />);
    const chips = within(screen.getByRole("group", { name: "Months in your data" }));
    const box = screen.getByLabelText("Your question") as HTMLTextAreaElement;

    expect(chips.getByRole("button", { name: /Mar 2022.*1 day/ })).toBeTruthy();
    expect(chips.getByRole("button", { name: /Jun 2022.*29 of 30 days/ })).toBeTruthy();
    await user.type(box, "orders by state");
    await user.click(chips.getByRole("button", { name: "May 2022" }));
    expect(box.value).toBe("orders by state in May 2022");
    await user.click(chips.getByRole("button", { name: "All dates" }));
    expect(box.value).toBe("orders by state");
    expect(calls).toEqual([]);
  });
});
