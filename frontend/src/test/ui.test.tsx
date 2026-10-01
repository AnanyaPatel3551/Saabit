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

function runOut(plan: Plan): RunOut {
  return {
    verified: true, sentence: "Maharashtra had the highest revenue.", source: "template", note: null,
    card: {
      card_id: "abc-12345678", dataset_id: "abc", plan, sql: "SELECT 1", pandas_code: "df",
      verified: true, result: [{ state: "MAHARASHTRA", value: 1000, orders: 10 }], caveats: [],
      row_count: 10, sql_result: null, pandas_result: null, mismatches: [], created_at: "now",
    },
  };
}

/** A fake backend that records every request path and answers /plan and /run. */
function fakeBackend() {
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
    return Response.json({ error: { code: "not_found", message: "no" } }, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

afterEach(() => vi.unstubAllGlobals());

describe("Ask panel", () => {
  it("editing a plan chip calls /run and not /plan", async () => {
    const user = userEvent.setup();
    const { calls, fetchMock } = fakeBackend();
    render(<AskPanel datasetId="abc" llmDown={false} llmReason={null}
      onLlmChange={() => undefined} onEvidence={() => undefined} />);

    await user.type(screen.getByLabelText("Your question"), "top 5 states by revenue");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText("Maharashtra had the highest revenue.");
    expect(calls.filter((c) => c.includes("/plan"))).toHaveLength(1);

    calls.length = 0;
    await user.selectOptions(screen.getByLabelText("Metric"), "orders");
    await screen.findByText("Maharashtra had the highest revenue.");

    expect(calls).toHaveLength(1);
    expect(calls[0]).toBe("/api/datasets/abc/run");
    expect(calls.some((c) => c.includes("/plan"))).toBe(false);
    const sent = JSON.parse(String(fetchMock.mock.lastCall?.[1]?.body)) as Plan;
    expect(sent.metric).toBe("orders");
    expect(sent.group_by).toEqual(["state"]);
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
