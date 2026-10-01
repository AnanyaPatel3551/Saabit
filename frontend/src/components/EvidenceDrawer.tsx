import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { cardRowsCsvUrl, getCard, getCardRows } from "../api/client";
import type { Card, RowsOut } from "../api/types";
import { indianDigits } from "../lib/format";
import { ResultChart } from "./ResultChart";
import { VerifiedBadge } from "./VerifiedBadge";

const TABS = ["Chart", "Plan", "SQL", "pandas", "Rows", "Caveats"] as const;
type Tab = (typeof TABS)[number];

/** A card already in hand, or the id of one to fetch with GET /api/cards/{id}. */
export type EvidenceItem = Card | string;

/**
 * S4: everything behind one answer. Escape closes it, Tab stays inside it, and focus goes
 * back to the button that opened it.
 */
export function EvidenceDrawer({ items, onClose }: { items: EvidenceItem[]; onClose: () => void }) {
  const [index, setIndex] = useState(0);
  const [tab, setTab] = useState<Tab>("Chart");
  const [card, setCard] = useState<Card | null>(null);
  const [error, setError] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const closeHandler = useRef(onClose);
  closeHandler.current = onClose;

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") closeHandler.current();
    };
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("keydown", onEscape);
      opener?.focus();
    };
  }, []);

  useEffect(() => {
    const item = items[index];
    setError(null);
    if (typeof item !== "string") {
      setCard(item);
      return;
    }
    setCard(null);
    let live = true;
    getCard(item).then((c) => live && setCard(c))
      .catch((e: Error) => live && setError(e.message));
    return () => { live = false; };
  }, [items, index]);

  function onKeyDown(event: KeyboardEvent) {
    if (event.key !== "Tab" || !panelRef.current) return;
    const focusable = panelRef.current.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], select, input, [tabindex="0"]');
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function onTabKey(event: KeyboardEvent) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = TABS[(TABS.indexOf(tab) + step + TABS.length) % TABS.length];
    setTab(next);
    document.getElementById(`tab-${next}`)?.focus();
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60" onClick={onClose}>
      <div ref={panelRef} role="dialog" aria-modal="true" aria-labelledby="evidence-title"
        onKeyDown={onKeyDown} onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full max-w-3xl flex-col border-l border-line bg-panel shadow-2xl">
        <header className="flex items-center justify-between gap-3 border-b border-line p-4">
          <div className="flex flex-wrap items-center gap-3">
            <h2 id="evidence-title" className="font-display text-xl text-gold-soft">Evidence</h2>
            {card && <VerifiedBadge verified={card.verified} />}
            {items.length > 1 && (
              <span className="flex items-center gap-1 text-xs text-muted">
                <button type="button" disabled={index === 0} onClick={() => setIndex(index - 1)}
                  className="rounded border border-line px-2 disabled:opacity-40" aria-label="Previous card">‹</button>
                Card {index + 1} of {items.length}
                <button type="button" disabled={index === items.length - 1}
                  onClick={() => setIndex(index + 1)}
                  className="rounded border border-line px-2 disabled:opacity-40" aria-label="Next card">›</button>
              </span>
            )}
          </div>
          <button ref={closeRef} type="button" onClick={onClose}
            className="rounded border border-line px-3 py-1 text-sm text-muted hover:text-text">
            Close <span className="sr-only">evidence (Escape)</span>
          </button>
        </header>

        <div role="tablist" aria-label="Evidence views" className="flex gap-1 overflow-x-auto border-b border-line px-4">
          {TABS.map((t) => (
            <button key={t} id={`tab-${t}`} role="tab" type="button" aria-selected={tab === t}
              aria-controls="evidence-panel" tabIndex={tab === t ? 0 : -1}
              onClick={() => setTab(t)} onKeyDown={onTabKey}
              className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm ${tab === t
                ? "border-gold text-text" : "border-transparent text-muted hover:text-text"}`}>
              {t}
            </button>
          ))}
        </div>

        <div id="evidence-panel" role="tabpanel" aria-labelledby={`tab-${tab}`}
          className="flex-1 overflow-auto p-4">
          {error && <p role="alert" className="text-sm text-bad">{error}</p>}
          {!card && !error && <p className="text-sm text-muted">Loading the card…</p>}
          {card && <TabBody tab={tab} card={card} />}
        </div>
      </div>
    </div>
  );
}

function TabBody({ tab, card }: { tab: Tab; card: Card }) {
  const code = "overflow-auto whitespace-pre rounded-lg border border-line bg-ink p-3 font-mono text-xs text-text";
  switch (tab) {
    case "Chart":
      return card.verified ? <ResultChart plan={card.plan} rows={card.result} /> : (
        <div className="grid gap-4 sm:grid-cols-2">
          <div><h3 className="mb-2 text-sm text-muted">SQL result</h3>
            <ResultChart plan={card.plan} rows={card.sql_result ?? []} /></div>
          <div><h3 className="mb-2 text-sm text-muted">pandas result</h3>
            <ResultChart plan={card.plan} rows={card.pandas_result ?? []} /></div>
        </div>
      );
    case "Plan":
      return <pre className={code}>{JSON.stringify(card.plan, null, 2)}</pre>;
    case "SQL":
      return <pre className={code}>{card.sql}</pre>;
    case "pandas":
      return <pre className={code}>{card.pandas_code}</pre>;
    case "Rows":
      return <RowsTab card={card} />;
    case "Caveats":
      return (
        <div className="space-y-3 text-sm">
          {card.caveats.length === 0 && card.mismatches.length === 0
            && <p className="text-muted">No caveats for this answer.</p>}
          <ul className="list-disc space-y-1 pl-5">
            {card.caveats.map((c) => <li key={c}>{c}</li>)}
          </ul>
          {card.mismatches.length > 0 && (
            <>
              <h3 className="text-amber">Where the engines disagreed</h3>
              <ul className="list-disc space-y-1 pl-5">{card.mismatches.map((m) => <li key={m}>{m}</li>)}</ul>
            </>
          )}
          <p className="text-xs text-muted">Card {card.card_id} · created {card.created_at}</p>
        </div>
      );
  }
}

function RowsTab({ card }: { card: Card }) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<RowsOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setError(null);
    getCardRows(card.card_id, page).then((d) => live && setData(d))
      .catch((e: Error) => live && setError(e.message));
    return () => { live = false; };
  }, [card.card_id, page]);

  const columns = data?.rows[0] ? Object.keys(data.rows[0]) : [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted">
        <span>{indianDigits(card.row_count)} cleaned rows behind this answer</span>
        <a href={cardRowsCsvUrl(card.card_id)} download className="text-gold hover:underline">
          Download all rows (CSV)
        </a>
      </div>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      {data && (
        <>
          <div className="max-h-[55vh] overflow-auto rounded-lg border border-line">
            <table className="w-full text-xs">
              <caption className="sr-only">Source rows, page {data.page} of {data.pages}</caption>
              <thead className="sticky top-0 bg-raised text-left text-muted">
                <tr>{columns.map((c) => <th key={c} scope="col" className="px-2 py-1 font-normal">{c}</th>)}</tr>
              </thead>
              <tbody>
                {data.rows.map((row, i) => (
                  <tr key={i} className="border-t border-line">
                    {columns.map((c) => <td key={c} className="whitespace-nowrap px-2 py-1">{String(row[c] ?? "")}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between text-sm">
            <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}
              className="rounded border border-line px-3 py-1 disabled:opacity-40">Previous</button>
            <span className="text-muted">Page {data.page} of {Math.max(data.pages, 1)}</span>
            <button type="button" disabled={page >= data.pages} onClick={() => setPage(page + 1)}
              className="rounded border border-line px-3 py-1 disabled:opacity-40">Next</button>
          </div>
        </>
      )}
    </div>
  );
}
