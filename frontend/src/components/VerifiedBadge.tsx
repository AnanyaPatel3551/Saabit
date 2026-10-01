/** Verified state shown as text plus an icon, never by colour alone (PRD Accessibility). */
export function VerifiedBadge({ verified }: { verified: boolean }) {
  return verified ? (
    <span
      className="inline-flex items-center gap-1 rounded-full border border-ok/50 bg-ok/10 px-2 py-0.5 text-xs font-medium text-ok"
      title="SQL and pandas computed the same result"
    >
      <svg aria-hidden="true" viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none"
        stroke="currentColor" strokeWidth="2.2">
        <path d="M3 8.5l3.2 3L13 4.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Verified
    </span>
  ) : (
    <span
      className="inline-flex items-center gap-1 rounded-full border border-amber/60 bg-amber/10 px-2 py-0.5 text-xs font-medium text-amber"
      title="SQL and pandas disagreed"
    >
      <svg aria-hidden="true" viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none"
        stroke="currentColor" strokeWidth="2">
        <path d="M8 2.5l6 11H2z" strokeLinejoin="round" />
        <path d="M8 6.5v3.2M8 11.6v.2" strokeLinecap="round" />
      </svg>
      Not verified
    </span>
  );
}
