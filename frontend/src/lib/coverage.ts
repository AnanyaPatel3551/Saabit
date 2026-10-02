// How many days of each month the data covers, from the dataset's first and last date.
// Labels only (chart tags, headline); the same rule as backend core/coverage.py: a month is
// partial when the date range misses its first or its last calendar day.

export interface MonthCover {
  month: string; // "2022-03"
  days: number;
  of: number;
  partial: boolean;
  /** "only 1 day" or "29 of 30 days". */
  note: string;
}

export type Coverage = Record<string, MonthCover>;

function parse(day: string): Date {
  const [y, m, d] = day.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

const DAY_MS = 86_400_000;

export function monthCoverage(min: string | null | undefined, max: string | null | undefined): Coverage {
  if (!min || !max) return {};
  const first = parse(min);
  const last = parse(max);
  if (Number.isNaN(first.getTime()) || Number.isNaN(last.getTime()) || last < first) return {};
  const out: Coverage = {};
  let cursor = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), 1));
  while (cursor <= last) {
    const y = cursor.getUTCFullYear();
    const m = cursor.getUTCMonth();
    const of = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    const start = cursor < first ? first : cursor;
    const monthEnd = new Date(Date.UTC(y, m, of));
    const end = monthEnd > last ? last : monthEnd;
    const days = Math.round((end.getTime() - start.getTime()) / DAY_MS) + 1;
    const month = `${y}-${String(m + 1).padStart(2, "0")}`;
    out[month] = { month, days, of, partial: days < of,
                   note: days === 1 ? "only 1 day" : `${days} of ${of} days` };
    cursor = new Date(Date.UTC(y, m + 1, 1));
  }
  return out;
}

export function partialOnly(coverage: Coverage): MonthCover[] {
  return Object.values(coverage).filter((c) => c.partial);
}
