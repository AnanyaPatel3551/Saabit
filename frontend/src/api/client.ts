// Every call to the backend goes through here. Non-2xx responses become one ApiError
// carrying the backend's readable message ({"error": {"code", "message"}}).

import { forgetKey, keyFor, keyForCard, rememberKey } from "../lib/datasetKeys";
import type {
  Card, DataCheck, Dataset, EvalSummary, Health, Overview, Plan, PlanOut, RowsOut, RunOut, SentenceOut,
} from "./types";

/** The header that carries an upload's private access key (never a URL parameter). */
export const KEY_HEADER = "X-Dataset-Key";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  /** The server's X-Request-ID, shown small under an error so a report can be traced. */
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, requestId: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

/** Add the access key header when this browser holds a key (the shared sample has none). */
function withKey(key: string | null, init: RequestInit = {}): RequestInit {
  if (!key) return init;
  const headers = new Headers(init.headers);
  headers.set(KEY_HEADER, key);
  return { ...init, headers };
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError(0, "network",
      "Could not reach the Saabit server. Check your connection and try again.");
  }
  if (!response.ok) {
    let code = "http_error";
    let message = `The request failed (HTTP ${response.status}).`;
    try {
      const body = await response.json();
      if (body?.error?.message) {
        code = body.error.code;
        message = body.error.message;
      }
    } catch {
      // keep the generic message
    }
    throw new ApiError(response.status, code, message, response.headers.get("X-Request-ID"));
  }
  return response;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return (await (await send(path, init)).json()) as T;
}

/** Keep a new upload's access key in this tab only, and leave it out of the returned dataset. */
function keepKey(created: Dataset & { access_key?: string }): Dataset {
  const { access_key: key, ...dataset } = created;
  if (key) rememberKey(dataset.dataset_id, key);
  return dataset;
}

const forDataset = (datasetId: string, init?: RequestInit) => withKey(keyFor(datasetId), init);
const forCard = (cardId: string, init?: RequestInit) => withKey(keyForCard(cardId), init);

function postJson(body: unknown): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) };
}

export function getHealth(): Promise<Health> {
  return request("/api/health");
}

export function uploadDataset(file: File): Promise<Dataset> {
  const form = new FormData();
  form.append("file", file);
  return request<Dataset>("/api/datasets", { method: "POST", body: form }).then(keepKey);
}

export function loadSample(): Promise<Dataset> {
  return request("/api/datasets/sample", { method: "POST" });
}

/** A copy of the synthetic Shopify-style file, with roles to confirm (not real data). */
export function loadShopifySample(): Promise<Dataset> {
  return request<Dataset>("/api/datasets/sample/shopify", { method: "POST" }).then(keepKey);
}

/** Delete an uploaded dataset now (raw file, cleaned data, evidence cards). Not the sample. */
export async function deleteDataset(datasetId: string): Promise<{ deleted: string }> {
  const deleted = await request<{ deleted: string }>(`/api/datasets/${datasetId}`,
    forDataset(datasetId, { method: "DELETE" }));
  forgetKey(datasetId);
  return deleted;
}

export function getEvalSummary(): Promise<EvalSummary> {
  return request("/api/eval-summary");
}

export function getDataset(datasetId: string): Promise<Dataset> {
  return request(`/api/datasets/${datasetId}`, forDataset(datasetId));
}

export function confirmRoles(
  datasetId: string, roles: Record<string, string | null>,
): Promise<DataCheck> {
  return request(`/api/datasets/${datasetId}/confirm`, forDataset(datasetId, postJson({ roles })));
}

export function getOverview(datasetId: string): Promise<Overview> {
  return request(`/api/datasets/${datasetId}/overview`, forDataset(datasetId));
}

export function planQuestion(datasetId: string, question: string): Promise<PlanOut> {
  return request(`/api/datasets/${datasetId}/plan`, forDataset(datasetId, postJson({ question })));
}

/** Both engines, no LLM: the numbers come back first. */
export function runPlan(datasetId: string, plan: Plan): Promise<RunOut> {
  return request(`/api/datasets/${datasetId}/run`, forDataset(datasetId, postJson(plan)));
}

/** The answer sentence for a card, written after the numbers are on screen. */
export function writeSentence(
  cardId: string, question: string, signal?: AbortSignal,
): Promise<SentenceOut> {
  return request(`/api/cards/${cardId}/sentence`, forCard(cardId, { ...postJson({ question }), signal }));
}

export function getCard(cardId: string): Promise<Card> {
  return request(`/api/cards/${cardId}`, forCard(cardId));
}

export function getCardRows(cardId: string, page: number): Promise<RowsOut> {
  return request(`/api/cards/${cardId}/rows?page=${page}`, forCard(cardId));
}

/** Fetch a CSV with the access key header and hand it to the browser as a download.
 * A plain link cannot send a header, so the file is saved from a temporary blob URL. */
async function downloadCsv(path: string, init: RequestInit, filename: string): Promise<void> {
  const blob = await (await send(path, init)).blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Every cleaned row behind a card, as a CSV download. */
export function downloadCardRows(cardId: string): Promise<void> {
  return downloadCsv(`/api/cards/${cardId}/rows?format=csv`, forCard(cardId), `rows_${cardId}.csv`);
}

/** The full fix log, as a CSV download. */
export function downloadFixes(datasetId: string): Promise<void> {
  return downloadCsv(`/api/datasets/${datasetId}/fixes`, forDataset(datasetId),
    `fixes_${datasetId}.csv`);
}
