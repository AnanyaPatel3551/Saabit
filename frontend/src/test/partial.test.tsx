import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ResultRow } from "../api/types";
import { headline } from "../components/AnswerCards";
import { EvidenceChart } from "../components/EvidenceChart";
import { monthCoverage } from "../lib/coverage";
import { okPlan } from "../lib/plan";

const coverage = monthCoverage("2022-03-31", "2022-06-29");
const trend = okPlan({ metric: "revenue", group_by: ["month"] });
const rows: ResultRow[] = [
  { month: "2022-03", value: 94810, orders: 158 },
  { month: "2022-04", value: 26234520, orders: 45858 },
  { month: "2022-05", value: 23953534, orders: 39221 },
  { month: "2022-06", value: 21390530, orders: 35141 },
];

describe("Month coverage", () => {
  it("marks a month cut short at the start edge and one cut short at the end edge", () => {
    expect(coverage["2022-03"]).toMatchObject({ partial: true, days: 1, of: 31, note: "only 1 day" });
    expect(coverage["2022-04"].partial).toBe(false);
    expect(coverage["2022-06"]).toMatchObject({ partial: true, days: 29, of: 30, note: "29 of 30 days" });
  });
});

describe("The answer chart", () => {
  it("tags partial months with the days they hold and keeps them visible", () => {
    render(<EvidenceChart plan={trend} rows={rows} coverage={coverage} />);

    const chart = screen.getByTestId("evidence-chart");
    expect(within(chart).getByText("only 1 day")).toBeTruthy();
    expect(within(chart).getByText("29 of 30 days")).toBeTruthy();
    const partial = chart.querySelectorAll("[data-partial]");
    expect(partial).toHaveLength(2);
    expect((partial[0] as HTMLElement).style.minHeight).toBe("4px");
  });

  it("draws the same thing wherever it is used", () => {
    const first = render(<EvidenceChart plan={trend} rows={rows} coverage={coverage} />);
    const html = first.container.innerHTML;
    first.unmount();

    const second = render(<EvidenceChart plan={trend} rows={rows} coverage={coverage} />);
    expect(second.container.innerHTML).toBe(html);
  });
});

describe("The headline number", () => {
  it("says how many days a partial latest month has instead of 'latest'", () => {
    expect(headline(trend, rows, coverage)?.label).toBe("Jun 2022 (29 of 30 days)");
    expect(headline(trend, rows.slice(0, 3), coverage)?.label).toBe("May 2022 (latest)");
  });
});
