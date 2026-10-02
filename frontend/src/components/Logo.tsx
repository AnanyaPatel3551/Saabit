/** The Saabit seal: a double ring with a tick, like a stamp on a checked document. */
export function Seal({ size = 28, className = "" }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true"
      className={`text-gold ${className}`}>
      <circle cx="16" cy="16" r="14.5" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="16" cy="16" r="11" stroke="currentColor" strokeWidth="1" strokeDasharray="1.6 1.9" />
      <path d="M10.5 16.5l3.6 3.6 7.4-8.2" stroke="currentColor" strokeWidth="2.2"
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Seal plus the serif wordmark. */
export function Logo({ size = 28, wordClass = "text-xl" }: { size?: number; wordClass?: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <Seal size={size} />
      <span className={`font-display text-gold ${wordClass}`}>Saabit</span>
    </span>
  );
}
