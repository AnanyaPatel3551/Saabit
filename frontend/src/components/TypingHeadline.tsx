import { useEffect, useState } from "react";

const STEP_MS = 40;  // per letter; two lines of about 28 letters each, plus a pause ≈ 2.5 s
const LINE_PAUSE_MS = 250;

let playedThisLoad = false;  // type once per page load; a later visit shows the full text

function reducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * The landing headline, typed in letter by letter with a thin caret. The full text is laid
 * out invisibly underneath from the start, so nothing below moves while it types. Screen
 * readers get the whole headline at once from aria-label; the typed letters are aria-hidden.
 */
export function TypingHeadline({ first, second, onDone }: {
  first: string;
  second: string;
  onDone?: () => void;
}) {
  const total = first.length + second.length;
  const [typed, setTyped] = useState(() => (playedThisLoad || reducedMotion() ? total : 0));
  const done = typed >= total;

  useEffect(() => {
    if (done) {
      playedThisLoad = true;
      onDone?.();
      return;
    }
    const delay = typed === first.length ? LINE_PAUSE_MS : STEP_MS;
    const timer = setTimeout(() => setTyped((n) => n + 1), delay);
    return () => clearTimeout(timer);
  }, [typed, done, first.length, onDone]);

  const line1 = first.slice(0, Math.min(typed, first.length));
  const line2 = second.slice(0, Math.max(typed - first.length, 0));
  const caretOnFirst = !done && typed < first.length;

  return (
    <h1 aria-label={`${first} ${second}`}
      className="font-display text-4xl leading-tight text-text sm:text-5xl">
      <Line full={first} shown={line1} caret={caretOnFirst} />
      <Line full={second} shown={line2} caret={!done && !caretOnFirst} gold />
    </h1>
  );
}

function Line({ full, shown, caret, gold }: {
  full: string;
  shown: string;
  caret: boolean;
  gold?: boolean;
}) {
  return (
    <span aria-hidden="true" className={`relative block ${gold ? "text-gold-soft" : ""}`}>
      <span className="invisible">{full}</span>
      <span className="absolute inset-0">
        {shown}
        {caret && <span className="typing-caret" />}
      </span>
    </span>
  );
}
