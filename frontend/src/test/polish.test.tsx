import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { stageFor } from "../App";
import type { Dataset, Health, Plan, RunOut } from "../api/types";
import { AiStatus, aiState } from "../components/AiStatus";
import { AskPanel } from "../components/AskPanel";
import { HowWeTest } from "../components/HowWeTest";
import { loadHistory, saveHistory } from "../lib/history";

const WRITTEN = "Maharashtra had the highest revenue.";

function runOut(plan: Plan): RunOut {
  return {
    verified: true, sentence: "Top 1 by revenue: Maharashtra (₹1,000).", source: "template",
    sentence_status: "pending", note: null,
    card: {
      card_id: "abc-12345678", dataset_id: "abc", plan, sql: "SELECT 1", pandas_code: "df",
      verified: true, result: [{ state: "Maharashtra", value: 1000, orders: 10 }], caveats: [],
      row_count: 10, sql_result: null, pandas_result: null, mismatches: [], created_at: "now",
    },
  };
}

function fakeBackend() {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/run")) return Response.json(runOut(JSON.parse(String(init?.body)) as Plan));
    if (url.includes("/sentence")) return Response.json({ sentence: WRITTEN, source: "llm", note: null });
    return Response.json({ error: { code: "x", message: "no" } }, { status: 404 });
  }));
}

function panel() {
  return <AskPanel datasetId="abc" llmDown={false} llmReason={null}
    onLlmChange={() => undefined} onEvidence={() => undefined} />;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});


/** Tap an example chip (it only fills the box), then press Ask. */
async function askExample(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(screen.getByRole("button", { name }));
  await user.click(screen.getByRole("button", { name: "Ask" }));
}

describe("Question history", () => {
  it("keeps answers after a reload, newest first, and Clear empties it", async () => {
    const user = userEvent.setup();
    fakeBackend();
    const first = render(panel());
    await askExample(user, "Top 5 states by revenue");
    await screen.findByText(WRITTEN);
    await askExample(user, "Monthly revenue trend");
    expect(await screen.findAllByText(WRITTEN)).toHaveLength(2);
    first.unmount();

    render(panel());  // a reload: the thread comes back from localStorage

    const questions = screen.getAllByText(/Top 5 states by revenue|Monthly revenue trend/, {
      selector: "li > p, li > button" });
    expect(questions.map((q) => q.textContent?.replace("Question: ", ""))).toEqual(
      ["Monthly revenue trend", "Top 5 states by revenue"]);
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByText(WRITTEN)).toBeNull();
    expect(loadHistory("abc")).toEqual([]);
  });

  it("does not crash when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });

    expect(() => saveHistory("abc", [])).not.toThrow();
    expect(loadHistory("abc")).toEqual([]);
    render(panel());
    expect(screen.getByText("Ask your first question — or tap an example.")).toBeTruthy();
  });

  it("shows the first-question hint and what Checked twice means only before the first question", async () => {
    const user = userEvent.setup();
    fakeBackend();
    render(panel());
    expect(screen.getByText(/worked out in two separate ways/)).toBeTruthy();

    await askExample(user, "Top 5 states by revenue");
    await screen.findByText(WRITTEN);

    expect(screen.queryByText("Ask your first question — or tap an example.")).toBeNull();
  });
});

function health(llm: Partial<Health["llm"]>): Health {
  return { status: "ok", version: "0.1.0", llm: {
    provider: "groq", model: "m", status: "ok", reason: null, checked_at: null, state: "ok",
    providers: [{ name: "groq", model: "m", configured: true, cooling_until: null },
                { name: "nim", model: "n", configured: true, cooling_until: null }], ...llm } };
}

describe("AI status in the header", () => {
  it("works out the AI state without showing provider names", () => {
    expect(aiState(health({}))).toBe("groq");
    expect(aiState(health({ state: "fallback", provider: "nim" }))).toBe("backup");
    expect(aiState(health({ state: "down", status: "unavailable" }))).toBe("paused");
    expect(aiState(health({ state: "unknown", status: "unknown" }))).toBe("groq");
  });

  it("shows text, not only a coloured dot", () => {
    render(<AiStatus health={health({ state: "fallback", provider: "nim" })} />);
    expect(screen.getByText("AI: using backup")).toBeTruthy();
  });

  it("says the AI is busy but numbers are still exact when no provider works", () => {
    render(<AiStatus health={health({ status: "not_configured", state: "down" })} />);
    expect(screen.getByText("AI: busy — numbers still exact")).toBeTruthy();
  });
});

describe("How we test page", () => {
  it("shows pending for anything not produced yet", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ eval: null, baseline: null, tests: null })));

    render(<HowWeTest />);

    expect((await screen.findAllByText("pending")).length).toBeGreaterThanOrEqual(6);
  });

  it("shows the latest eval when it exists", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({
      eval: { answerable: { correct: 38, total: 40 }, refused: { correct: 10, total: 10 },
              verified_but_wrong: 0, anchors_answerable: { correct: 13, total: 13 },
              anchors_refused: { correct: 2, total: 2 }, served_by: ["nim nemotron"],
              finished_at: "2026-10-02 01:07", used_saved_plans: false },
      baseline: null, tests: { passed: 378, skipped: 2, date: "2026-10-02" } })));

    render(<HowWeTest />);

    expect(await screen.findByText("38 of 40")).toBeTruthy();
    expect(screen.getByText("378 (2026-10-02)")).toBeTruthy();
  });
});

describe("Opening a dataset", () => {
  const base = { dataset_id: "abc", filename: "f.csv", size_bytes: 1, rows: 1, created_at: "",
                 columns: [], roles: [], missing_required: [], unmapped_columns: [] };

  it("goes straight to the workspace for the sample, whose roles are confirmed", () => {
    const check = { dataset_id: "abc", rows_in: 1, rows_out: 1, partial_months: [],
                    unknown_states: [], fixes: [], capability: { can_answer: [], cannot_answer: [] } };
    const sample = { ...base, roles_confirmed: true, data_check: check } as Dataset;

    expect(stageFor(sample).name).toBe("workspace");
  });

  it("shows the confirm screen for an upload", () => {
    const upload = { ...base, roles_confirmed: false, data_check: null } as Dataset;

    expect(stageFor(upload).name).toBe("confirm");
  });
});
