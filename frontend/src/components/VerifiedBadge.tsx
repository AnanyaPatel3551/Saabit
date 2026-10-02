export const CHECKED_TWICE_HELP =
  "Saabit worked out this number in two separate ways and both gave the same result.";
export const NOT_CHECKED_HELP = "Couldn't double-check this number, so we're not showing it.";

/** "Checked twice" shown as text plus an icon, never by colour alone (PRD Accessibility).
 * The explanation is in the tooltip and, for screen readers and taps, in the label itself. */
export function VerifiedBadge({ verified }: { verified: boolean }) {
  return verified ? (
    <span tabIndex={0} title={CHECKED_TWICE_HELP} aria-label={`Checked twice. ${CHECKED_TWICE_HELP}`}
      className="inline-flex items-center gap-1 rounded-full border border-ok/50 bg-ok/10 px-2 py-0.5 text-xs font-medium text-ok"
    >
      <svg aria-hidden="true" viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none"
        stroke="currentColor" strokeWidth="2.2">
        <path d="M3 8.5l3.2 3L13 4.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Checked twice
    </span>
  ) : (
    <span tabIndex={0} title={NOT_CHECKED_HELP} aria-label={`Not checked. ${NOT_CHECKED_HELP}`}
      className="inline-flex items-center gap-1 rounded-full border border-amber/60 bg-amber/10 px-2 py-0.5 text-xs font-medium text-amber"
    >
      <svg aria-hidden="true" viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none"
        stroke="currentColor" strokeWidth="2">
        <path d="M8 2.5l6 11H2z" strokeLinejoin="round" />
        <path d="M8 6.5v3.2M8 11.6v.2" strokeLinecap="round" />
      </svg>
      Couldn't double-check
    </span>
  );
}
