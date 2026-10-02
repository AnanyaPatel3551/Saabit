// The question thread for one dataset, kept in this browser only (localStorage). No account,
// nothing sent anywhere. Storage can be full, blocked or unavailable: every call fails
// silently, and the thread then simply lasts until the page closes.

import type { Plan, ResultRow, RunOut } from "../api/types";

export const MAX_ENTRIES = 20;
export const MAX_ROWS = 50;  // keeps each saved card small; the evidence drawer has the rest

/** Shown text for an answer: the LLM's sentence, or the template; pending until written. */
export type Sentence = { status: "pending" } | { status: "done"; text: string | null; source: string };

export interface HistoryEntry {
  id: string;
  question: string;
  askedAt: string;
  /** An answer from /run (verified or not), or a refusal from /plan. */
  run?: RunOut;
  caveats: string[];
  sentence?: Sentence;
  refusal?: Plan;
}

const key = (datasetId: string) => `saabit:history:${datasetId}`;

function trimRows(rows: ResultRow[] | null): ResultRow[] | null {
  return rows ? rows.slice(0, MAX_ROWS) : rows;
}

/** What is saved: at most MAX_ENTRIES, rows capped, a pending sentence saved as the template. */
function forStorage(entries: HistoryEntry[]): HistoryEntry[] {
  return entries.slice(0, MAX_ENTRIES).map((entry) => {
    if (!entry.run) return entry;
    const card = entry.run.card;
    const sentence = entry.sentence?.status === "pending"
      ? { status: "done" as const, text: entry.run.sentence, source: entry.run.source }
      : entry.sentence;
    return {
      ...entry, sentence,
      run: { ...entry.run, card: { ...card, result: trimRows(card.result) ?? [],
                                   sql_result: trimRows(card.sql_result),
                                   pandas_result: trimRows(card.pandas_result) } },
    };
  });
}

export function loadHistory(datasetId: string): HistoryEntry[] {
  try {
    const saved = window.localStorage.getItem(key(datasetId));
    const parsed: unknown = saved ? JSON.parse(saved) : [];
    return Array.isArray(parsed) ? (parsed as HistoryEntry[]).slice(0, MAX_ENTRIES) : [];
  } catch {
    return [];
  }
}

export function saveHistory(datasetId: string, entries: HistoryEntry[]): void {
  try {
    window.localStorage.setItem(key(datasetId), JSON.stringify(forStorage(entries)));
  } catch {
    // full or blocked storage: keep the thread in memory only
  }
}

export function clearHistory(datasetId: string): void {
  try {
    window.localStorage.removeItem(key(datasetId));
  } catch {
    // nothing to do
  }
}

export function newEntryId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}
