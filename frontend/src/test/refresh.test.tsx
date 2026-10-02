import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App, { OTHER_TAB_MESSAGE } from "../App";
import { GONE_MESSAGE } from "../components/ErrorNote";
import { forgetKey, rememberKey } from "../lib/datasetKeys";
import { saveHistory } from "../lib/history";
import { loadActive, saveActive } from "../lib/session";

const check = { dataset_id: "sample000000", rows_in: 1, rows_out: 1, partial_months: [],
  unknown_states: [], fixes: [], capability: { can_answer: [], cannot_answer: [] } };
const sample = { dataset_id: "sample000000", filename: "amazon_sale_report.csv.gz", size_bytes: 1,
  rows: 1, created_at: "", columns: [], roles: [], roles_confirmed: true, missing_required: [],
  unmapped_columns: [], data_check: check };

function backend(dataset: (url: string) => Response) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith("/api/datasets/") && !url.includes("/overview")) return dataset(url);
    if (url.includes("/overview")) return Response.json({ status: "computing" });
    return Response.json({ status: "ok", version: "x", llm: { provider: "groq", model: "m",
      status: "unknown", reason: null, checked_at: null, state: "unknown", providers: [] } });
  }));
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  forgetKey("up1234567890");
});
afterEach(() => vi.unstubAllGlobals());

describe("Refreshing the page", () => {
  it("reopens the sample with its question history", async () => {
    backend(() => Response.json(sample));
    saveActive({ id: "sample000000", sample: true });
    saveHistory("sample000000", [{ id: "1", question: "orders by state", askedAt: "", caveats: [],
      refusal: { status: "unsupported", metric: null, group_by: [], filters: [], date_range: null,
        sort: null, limit: null, clarification: null, unsupported_reason: "No." } }]);

    render(<App />);

    expect(await screen.findByText("orders by state")).toBeTruthy();
    expect(screen.getByText("amazon_sale_report.csv.gz")).toBeTruthy();
  });

  it("reopens an upload in the tab that holds its key", async () => {
    backend(() => Response.json({ ...sample, dataset_id: "up1234567890", filename: "mine.csv" }));
    rememberKey("up1234567890", "k");
    saveActive({ id: "up1234567890", sample: false });

    render(<App />);

    expect(await screen.findByText("mine.csv")).toBeTruthy();
  });

  it("says the file was removed after 24 hours when the server no longer has it", async () => {
    backend(() => Response.json({ error: { code: "dataset_not_found", message: "No dataset" } },
      { status: 404 }));
    rememberKey("up1234567890", "k");
    saveActive({ id: "up1234567890", sample: false });

    render(<App />);

    expect(await screen.findByText(GONE_MESSAGE)).toBeTruthy();
    expect(loadActive()).toBeNull();
  });

  it("does not try to open an upload from a tab without its key", () => {
    backend(() => Response.json(sample));
    saveActive({ id: "up1234567890", sample: false });

    render(<App />);

    expect(screen.getByText(OTHER_TAB_MESSAGE)).toBeTruthy();
    expect(loadActive()).toBeNull();
  });
});
