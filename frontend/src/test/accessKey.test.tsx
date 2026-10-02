import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  deleteDataset, downloadCardRows, getCardRows, getOverview, KEY_HEADER, runPlan, uploadDataset,
} from "../api/client";
import { CsvDownload } from "../components/CsvDownload";
import { okPlan } from "../lib/plan";

const KEY = "s3cret-key-from-the-server";

type Call = { url: string; key: string | null };

/** A backend that returns a fresh upload with its key, and records each call's URL and key. */
function backend(): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, key: new Headers(init?.headers).get(KEY_HEADER) });
    if (url === "/api/datasets") {
      return Response.json({ dataset_id: "abc123456789", filename: "a.csv", access_key: KEY });
    }
    if (url.includes("format=csv")) return new Response("order_id\n1\n");
    if (init?.method === "DELETE") return Response.json({ deleted: "abc123456789" });
    return Response.json({});
  }));
  return calls;
}

beforeEach(() => {
  sessionStorage.clear();
  URL.createObjectURL = vi.fn(() => "blob:rows");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.unstubAllGlobals());

describe("Access key for an upload", () => {
  it("is kept in this tab's sessionStorage and left out of the returned dataset", async () => {
    backend();

    const dataset = await uploadDataset(new File(["a"], "a.csv"));

    expect("access_key" in dataset).toBe(false);
    expect(sessionStorage.getItem("saabit-key:abc123456789")).toBe(KEY);
    expect(localStorage.getItem("saabit-key:abc123456789")).toBeNull();
  });

  it("is sent as a header on dataset and card calls, and never in a URL", async () => {
    const calls = backend();
    await uploadDataset(new File(["a"], "a.csv"));

    await getOverview("abc123456789");
    await runPlan("abc123456789", okPlan({ metric: "orders" }));
    await getCardRows("abc123456789-0a1b2c3d", 1);
    await downloadCardRows("abc123456789-0a1b2c3d");

    const after = calls.slice(1);
    expect(after.map((c) => c.key)).toEqual([KEY, KEY, KEY, KEY]);
    expect(calls.every((c) => !c.url.includes(KEY))).toBe(true);
  });

  it("is not sent for the shared sample, which has none", async () => {
    const calls = backend();

    await getOverview("sample000000");

    expect(calls[0].key).toBeNull();
  });

  it("is forgotten after the dataset is deleted", async () => {
    backend();
    await uploadDataset(new File(["a"], "a.csv"));

    await deleteDataset("abc123456789");

    expect(sessionStorage.getItem("saabit-key:abc123456789")).toBeNull();
  });
});

describe("CSV download button", () => {
  it("fetches the rows with the key and saves them from a blob URL", async () => {
    const user = userEvent.setup();
    const calls = backend();
    await uploadDataset(new File(["a"], "a.csv"));
    render(<CsvDownload label="Download all rows (CSV)" className=""
      download={() => downloadCardRows("abc123456789-0a1b2c3d")} />);

    await user.click(screen.getByRole("button", { name: "Download all rows (CSV)" }));

    expect(calls.at(-1)).toEqual({ url: "/api/cards/abc123456789-0a1b2c3d/rows?format=csv", key: KEY });
    expect(URL.createObjectURL).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:rows");
  });
});
