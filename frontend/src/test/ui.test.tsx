import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Plan, RunOut } from "../api/types";
import { RefusalCard } from "../components/AnswerCards";
import { AskPanel } from "../components/AskPanel";
import { VerifiedBadge } from "../components/VerifiedBadge";
import { okPlan } from "../lib/plan";

const plannedQuestion = okPlan({ metric: "revenue", group_by: ["state"],
  sort: { by: "value", dir: "desc" }, limit: 5 });

const TEMPLATE = "Top 1 by revenue: Maharashtra (₹1,000).";
const WRITTEN = "Maharashtra had the highest revenue.";

function runOut(plan: Plan): RunOut {
  return {
    verified: true, sentence: TEMPLATE, source: "template", sentence_status: "pending", note: null,
    card: {
      card_id: "abc-12345678", dataset_id: "abc", plan, sql: "SELECT 1", pandas_code: "df",
      verified: true, result: [{ state: "MAHARASHTRA", value: 1000, orders: 10 }], caveats: [],
      row_count: 10, sql_result: null, pandas_result: null, mismatches: [], created_at: "now",
    },
  };
}

/**
 * A fake backend that records every request path and answers /plan, /run and the card
 * sentence. `sentence` decides what the sentence call does (default: the written sentence).
 */
function fakeBackend(sentence: () => Promise<Response> = async () =>
  Response.json({ sentence: WRITTEN, source: "llm", note: null })) {
  const calls: string[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(url);
    if (url.includes("/plan")) {
      return Response.json({ plan: plannedQuestion, caveats: [], cached: false });
    }
    if (url.includes("/run")) {
      return Response.json(runOut(JSON.parse(String(init?.body)) as Plan));
    }
    if (url.includes("/sentence")) return sentence();
    return Response.json({ error: { code: "not_found", message: "no" } }, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

function renderPanel() {
  render(<AskPanel datasetId="abc" llmDown={false} llmReason={null}
    onLlmChange={() => undefined} onEvidence={() => undefined} />);
}

afterEach(() => vi.unstubAllGlobals());

describe("Ask panel", () => {
  it("editing a plan chip calls /run and not /plan", async () => {
    const user = userEvent.setup();
    const { calls, fetchMock } = fakeBackend();
    renderPanel();

    await user.type(screen.getByLabelText("Your question"), "top 5 states by revenue");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText(WRITTEN);
    expect(calls.filter((c) => c.includes("/plan"))).toHaveLength(1);

    calls.length = 0;
    await user.selectOptions(screen.getByLabelText("Metric"), "orders");
    await screen.findByText(WRITTEN);

    expect(calls.filter((c) => c.endsWith("/run"))).toEqual(["/api/datasets/abc/run"]);
    expect(calls.some((c) => c.includes("/plan"))).toBe(false);
    const runCall = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/run")).at(-1);
    const sent = JSON.parse(String(runCall?.[1]?.body)) as Plan;
    expect(sent.metric).toBe("orders");
    expect(sent.group_by).toEqual(["state"]);
  });

  it("shows the numbers before the sentence arrives", async () => {
    const user = userEvent.setup();
    let release: (value: Response) => void = () => undefined;
    fakeBackend(() => new Promise((resolve) => { release = resolve; }));
    renderPanel();

    await user.click(screen.getByRole("button", { name: "Top 5 states by revenue" }));

    expect(await screen.findByText("Writing the answer…")).toBeTruthy();
    expect(screen.getByText("Verified")).toBeTruthy();
    expect(screen.queryByText(WRITTEN)).toBeNull();
    release(Response.json({ sentence: WRITTEN, source: "llm", note: null }));
    expect(await screen.findByText(WRITTEN)).toBeTruthy();
  });

  it("shows the template sentence when the sentence call fails", async () => {
    const user = userEvent.setup();
    fakeBackend(async () => Response.json(
      { error: { code: "internal_error", message: "x" } }, { status: 500 }));
    renderPanel();

    await user.click(screen.getByRole("button", { name: "Top 5 states by revenue" }));

    expect(await screen.findByText(TEMPLATE)).toBeTruthy();
    expect(screen.getByText("Sentence written from a template.")).toBeTruthy();
  });
});

describe("Refusal card", () => {
  it("renders the suggested question as a clickable chip", async () => {
    const user = userEvent.setup();
    const onAsk = vi.fn();
    const plan = okPlan({
      status: "unsupported",
      unsupported_reason: "The file has no cost column, so profit cannot be computed. "
        + "Nearest question: revenue by category.",
    });
    render(<RefusalCard plan={plan} onAsk={onAsk} />);

    expect(screen.getByText(/profit cannot be computed/)).toBeTruthy();
    const chip = screen.getByRole("button", { name: "revenue by category" });
    await user.click(chip);
    expect(onAsk).toHaveBeenCalledWith("revenue by category");
  });
});

describe("Verified badge", () => {
  it("has a text label, not only a colour", () => {
    const { container } = render(<VerifiedBadge verified />);
    expect(within(container).getByText("Verified")).toBeTruthy();
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("says Not verified in words when the engines disagree", () => {
    render(<VerifiedBadge verified={false} />);
    expect(screen.getByText("Not verified")).toBeTruthy();
  });
});
