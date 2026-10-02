import { ApiError } from "../api/client";

/** Server messages that are already written for sellers and can be shown as they are. */
const PLAIN_CODES = new Set(["rate_limited", "invalid_plan", "invalid_roles", "not_cleaned",
  "empty_file", "file_too_large", "unsupported_file_type", "unreadable_file", "upload_error",
  "unknown_filter_value", "too_many_rows", "query_timeout", "forbidden"]);

export const GONE_MESSAGE = "Your file was removed after 24 hours for privacy. Please upload it again.";

/** One friendly line for any failure, plus the request id when the server sent one. */
export function friendlyError(error: unknown): { message: string; requestId: string | null } {
  if (!(error instanceof ApiError)) {
    return { message: "Something went wrong. Please try again.", requestId: null };
  }
  const requestId = error.requestId;
  if (error.code === "network") {
    return { message: "Could not reach Saabit. Check your connection and try again.", requestId };
  }
  if (error.code === "dataset_not_found" || error.code === "card_not_found") {
    return { message: GONE_MESSAGE, requestId };
  }
  if (error.code === "llm_unavailable") {
    return { message: "Saabit can't read typed questions right now. The example questions still work.",
             requestId };
  }
  if (PLAIN_CODES.has(error.code)) {
    return { message: error.message, requestId };
  }
  return { message: "Something went wrong on our side. Please try again.", requestId };
}

export function ErrorNote({ message, requestId }: { message: string; requestId: string | null }) {
  return (
    <div role="alert" className="rounded-lg border border-bad/60 bg-bad/10 p-3 text-sm text-text">
      <p>{message}</p>
      {requestId && <p className="mt-1 text-[11px] text-muted">Reference: {requestId}</p>}
    </div>
  );
}
