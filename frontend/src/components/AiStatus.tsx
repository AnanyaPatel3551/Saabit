import type { Health } from "../api/types";

export type AiState = "groq" | "backup" | "paused";

// No provider or model names: sellers only need to know whether typed questions work.
const LABELS: Record<AiState, string> = {
  groq: "AI: ready",
  backup: "AI: using backup",
  paused: "AI: busy — numbers still exact",
};

/** Which AI is answering, from /api/health: its last call, else which providers are usable. */
export function aiState(health: Health | null): AiState | null {
  if (!health) return null;
  const llm = health.llm;
  if (llm.status === "not_configured" || llm.state === "down") return "paused";
  if (llm.state === "fallback") return "backup";
  if (llm.state === "ok") return llm.provider === "groq" ? "groq" : "backup";
  const usable = (llm.providers ?? []).filter((p) => p.configured && !p.cooling_until);
  if (usable[0]?.name === "groq") return "groq";
  return usable.length ? "backup" : "paused";
}

/** A dot plus words; the dot's shape also changes, so colour is never the only signal. */
export function AiStatus({ health }: { health: Health | null }) {
  const state = aiState(health);
  if (!state) return null;
  return (
    <span role="status" className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs text-muted">
      <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
        {state === "groq" && <circle cx="5" cy="5" r="4" className="fill-ok" />}
        {state === "backup" && (
          <>
            <circle cx="5" cy="5" r="3.5" fill="none" className="stroke-amber" strokeWidth="1.2" />
            <path d="M5 1.5a3.5 3.5 0 0 1 0 7z" className="fill-amber" />
          </>
        )}
        {state === "paused" && (
          <circle cx="5" cy="5" r="3.5" fill="none" className="stroke-muted" strokeWidth="1.2" />
        )}
      </svg>
      {LABELS[state]}
    </span>
  );
}
