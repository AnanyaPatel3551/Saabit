import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DataCheck, Dataset, Plan, RunOut } from "../api/types";
import { AskPanel } from "../components/AskPanel";
import { Privacy } from "../components/Privacy";
import { Workspace } from "../components/Workspace";
import { loadHistory, saveHistory } from "../lib/history";

afterEach(() => vi.unstubAllGlobals());

function runOut(plan: Plan): RunOut {
  return {
    verified: true, sentence: "Answer.", source: "template", sentence_status: "final", note: null,
    card: { card_id: "abc-1", dataset_id: "abc", plan, sql: "", pandas_code: "", verified: true,
            result: [{ value: 1, orders: 1 }], caveats: [], row_count: 1, sql_result: null,
            pandas_result: null, mismatches: [], created_at: "" },
  };
}

/** A backend whose /plan and /run wait until release() is called. */
function slowBackend() {
  const calls: string[] = [];
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(url);
    await gate;
    if (url.endsWith("/plan")) {
      return Response.json({ plan: { status: "ok", metric: "orders", group_by: [], filters: [],
        date_range: null, sort: null, limit: null, clarification: null, unsupported_reason: null },
        caveats: [], cached: false });
    }
    return Response.json(runOut(JSON.parse(String(init?.body)) as Plan));
  }));
  return { calls, release: () => release() };
}

function panel() {
  return <AskPanel datasetId="abc" llmDown={false} llmReason={null}
    onLlmChange={() => undefined} onEvidence={() => undefined} />;
}

describe("Ask button", () => {
  it("always looks active; with an empty box a click only focuses the box", async () => {
    const user = userEvent.setup();
    const backend = slowBackend();
    render(panel());
    const ask = screen.getByRole("button", { name: "Ask" }) as HTMLButtonElement;

    expect(ask.disabled).toBe(false);
    expect(ask.className).toContain("bg-gold");
    await user.click(ask);
    expect(backend.calls).toEqual([]);
    expect(document.activeElement).toBe(screen.getByLabelText("Your question"));
  });

  it("Enter submits, and while asking it says Asking… and ignores extra clicks", async () => {
    const user = userEvent.setup();
    const backend = slowBackend();
    render(panel());

    await user.type(screen.getByLabelText("Your question"), "how many orders");
    await user.keyboard("{Enter}");
    const asking = await screen.findByRole("button", { name: "Asking…" });
    expect(asking.getAttribute("aria-disabled")).toBe("true");
    expect(asking.className).toContain("bg-gold");
    await user.click(asking);
    expect(backend.calls).toEqual(["/api/datasets/abc/plan"]);  // still one question
    backend.release();
    expect(await screen.findByRole("button", { name: "Ask" })).toBeTruthy();
  });

  it("an example chip only fills the box and focuses it; it never sends", async () => {
    const user = userEvent.setup();
    const backend = slowBackend();
    render(panel());

    await user.click(screen.getByRole("button", { name: "Monthly revenue trend" }));

    const box = screen.getByLabelText("Your question") as HTMLTextAreaElement;
    expect(box.value).toBe("Monthly revenue trend");
    await vi.waitFor(() => expect(document.activeElement).toBe(box));
    expect(box.selectionStart).toBe("Monthly revenue trend".length);
    expect(backend.calls).toEqual([]);
  });

  it("an example sent unchanged runs its ready plan, and the box is cleared", async () => {
    const user = userEvent.setup();
    const backend = slowBackend();
    render(panel());

    await user.click(screen.getByRole("button", { name: "Monthly revenue trend" }));
    const box = screen.getByLabelText("Your question");
    await vi.waitFor(() => expect(document.activeElement).toBe(box));
    await user.keyboard("{Enter}");

    expect(backend.calls).toEqual(["/api/datasets/abc/run"]);
    expect((screen.getByLabelText("Your question") as HTMLTextAreaElement).value).toBe("");
    backend.release();
  });

  it("Shift+Enter starts a new line instead of sending", async () => {
    const user = userEvent.setup();
    const backend = slowBackend();
    render(panel());

    await user.type(screen.getByLabelText("Your question"), "orders{Shift>}{Enter}{/Shift}by state");

    expect((screen.getByLabelText("Your question") as HTMLTextAreaElement).value).toBe("orders\nby state");
    expect(backend.calls).toEqual([]);
  });
});

const check: DataCheck = {
  dataset_id: "up1234567890", rows_in: 1, rows_out: 1, partial_months: [], unknown_states: [],
  fixes: [], capability: { can_answer: [], cannot_answer: [] },
};
const base = { dataset_id: "up1234567890", size_bytes: 1, rows: 1, created_at: "", columns: [],
               roles: [], roles_confirmed: true, missing_required: [], unmapped_columns: [],
               data_check: check };

function workspaceBackend(deleted: string[]) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "DELETE") {
      deleted.push(url);
      return Response.json({ deleted: "up1234567890" });
    }
    if (url.includes("/overview")) return Response.json({ status: "computing" });
    return Response.json({ status: "ok", version: "x", llm: { provider: "groq", model: "m",
      status: "unknown", reason: null, checked_at: null, state: "unknown", providers: [] } });
  }));
}

describe("Delete my data now", () => {
  it("is not offered for the shared sample", () => {
    workspaceBackend([]);
    const sample = { ...base, filename: "amazon_sale_report.csv.gz" } as Dataset;

    render(<Workspace dataset={sample} check={check} onBack={() => undefined} />);

    expect(screen.queryByRole("button", { name: "Delete my data now" })).toBeNull();
  });

  it("deletes an upload on the server, clears its history and goes back", async () => {
    const user = userEvent.setup();
    const deleted: string[] = [];
    workspaceBackend(deleted);
    saveHistory("up1234567890", [{ id: "1", question: "q", askedAt: "", caveats: [] }]);
    const onBack = vi.fn();
    const upload = { ...base, filename: "my_orders.csv" } as Dataset;
    render(<Workspace dataset={upload} check={check} onBack={onBack} />);

    await user.click(screen.getByRole("button", { name: "Delete my data now" }));
    await user.click(screen.getByRole("button", { name: "Yes, delete" }));

    expect(deleted).toEqual(["/api/datasets/up1234567890"]);
    expect(loadHistory("up1234567890")).toEqual([]);
    expect(onBack).toHaveBeenCalled();
  });
});

describe("Privacy page", () => {
  it("says what the AI provider receives and links to the providers' own policies", () => {
    render(<Privacy />);

    expect(screen.getByText(/deleted after 24 hours/)).toBeTruthy();
    expect(screen.getByText(/never receives raw rows/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Groq's privacy policy" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "NVIDIA's privacy policy" })).toBeTruthy();
  });
});
