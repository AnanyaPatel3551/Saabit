// Which dataset was open, so a refresh (F5) reopens it. Only the id is kept here; an upload's
// private key stays in this tab's sessionStorage (lib/datasetKeys.ts), which survives a
// refresh but not closing the tab. Storage can be blocked, so every access fails silently.

const ACTIVE = "saabit:active";

export interface ActiveDataset {
  id: string;
  sample: boolean;  // the shared sample needs no key and always restores
}

export function saveActive(active: ActiveDataset): void {
  try {
    localStorage.setItem(ACTIVE, JSON.stringify(active));
  } catch {
    // a refresh will simply start on the landing page
  }
}

export function loadActive(): ActiveDataset | null {
  try {
    const raw = localStorage.getItem(ACTIVE);
    const parsed = raw ? (JSON.parse(raw) as ActiveDataset) : null;
    return parsed && typeof parsed.id === "string" ? parsed : null;
  } catch {
    return null;
  }
}

export function clearActive(): void {
  try {
    localStorage.removeItem(ACTIVE);
  } catch {
    // nothing stored
  }
}
