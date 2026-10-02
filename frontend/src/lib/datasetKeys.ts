// Each upload's private access key, held only by this browser tab: in memory, and in
// sessionStorage so a reload in the same tab keeps working. Never put in a URL or in
// localStorage. Storage can be blocked, so every access fails silently.

const PREFIX = "saabit-key:";
const keys = new Map<string, string>();

/** Keep the key the server returned for a new upload. */
export function rememberKey(datasetId: string, key: string): void {
  keys.set(datasetId, key);
  try {
    sessionStorage.setItem(PREFIX + datasetId, key);
  } catch {
    // memory still has it for this page
  }
}

/** The key for a dataset, or null (the shared sample has none). */
export function keyFor(datasetId: string): string | null {
  const known = keys.get(datasetId);
  if (known) return known;
  try {
    const stored = sessionStorage.getItem(PREFIX + datasetId);
    if (stored) keys.set(datasetId, stored);
    return stored;
  } catch {
    return null;
  }
}

/** A card id starts with its dataset id ("<dataset id>-<random>"). */
export function keyForCard(cardId: string): string | null {
  return keyFor(cardId.split("-")[0]);
}

/** Drop a dataset's key, after it is deleted. */
export function forgetKey(datasetId: string): void {
  keys.delete(datasetId);
  try {
    sessionStorage.removeItem(PREFIX + datasetId);
  } catch {
    // nothing stored
  }
}
