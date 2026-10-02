import { useEffect, useState } from "react";
import { getOverview } from "../api/client";
import type { Overview } from "../api/types";

const POLL_MS = 2000;

/** /overview for a dataset, polled every 2 s while it is still "computing". */
export function useOverview(datasetId: string): { overview: Overview | null; error: string | null } {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const next = await getOverview(datasetId);
        if (!live) return;
        setOverview(next);
        if (next.status === "computing") timer = setTimeout(poll, POLL_MS);
      } catch (e) {
        if (live) setError((e as Error).message);
      }
    };
    void poll();
    return () => { live = false; clearTimeout(timer); };
  }, [datasetId]);

  return { overview, error };
}
