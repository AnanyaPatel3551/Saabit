// Every call to the backend goes through here. Non-2xx responses become one ApiError
// carrying the backend's readable message ({"error": {"code", "message"}}).

import type {
  Card, DataCheck, Dataset, Health, Overview, Plan, PlanOut, RowsOut, RunOut, SentenceOut,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
    throw new ApiError(response.status, code, message);
  }
  return (await response.json()) as T;
}

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
  return request("/api/datasets", { method: "POST", body: form });
}

export function loadSample(): Promise<Dataset> {
  return request("/api/datasets/sample", { method: "POST" });
}

export function getDataset(datasetId: string): Promise<Dataset> {
  return request(`/api/datasets/${datasetId}`);
}

export function confirmRoles(
  datasetId: string, roles: Record<string, string | null>,
): Promise<DataCheck> {
  return request(`/api/datasets/${datasetId}/confirm`, postJson({ roles }));
}

export function getOverview(datasetId: string): Promise<Overview> {
  return request(`/api/datasets/${datasetId}/overview`);
}

export function planQuestion(datasetId: string, question: string): Promise<PlanOut> {
  return request(`/api/datasets/${datasetId}/plan`, postJson({ question }));
}

/** Both engines, no LLM: the numbers come back first. */
export function runPlan(datasetId: string, plan: Plan): Promise<RunOut> {
  return request(`/api/datasets/${datasetId}/run`, postJson(plan));
}

/** The answer sentence for a card, written after the numbers are on screen. */
export function writeSentence(
  cardId: string, question: string, signal?: AbortSignal,
): Promise<SentenceOut> {
  return request(`/api/cards/${cardId}/sentence`, { ...postJson({ question }), signal });
}

export function getCard(cardId: string): Promise<Card> {
  return request(`/api/cards/${cardId}`);
}

export function getCardRows(cardId: string, page: number): Promise<RowsOut> {
  return request(`/api/cards/${cardId}/rows?page=${page}`);
}

export function cardRowsCsvUrl(cardId: string): string {
  return `/api/cards/${cardId}/rows?format=csv`;
}

export function fixesCsvUrl(datasetId: string): string {
  return `/api/datasets/${datasetId}/fixes`;
}
