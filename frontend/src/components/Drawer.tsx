import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";

/**
 * A panel that slides over from the right (full width on phones). Escape or a click outside
 * closes it, Tab stays inside, and focus returns to the button that opened it.
 */
export function Drawer({ title, onClose, children }: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const closeHandler = useRef(onClose);
  closeHandler.current = onClose;

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    close.current?.focus();
    const onEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") closeHandler.current();
    };
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("keydown", onEscape);
      opener?.focus();
    };
  }, []);

  function trapTab(event: KeyboardEvent) {
    if (event.key !== "Tab" || !panel.current) return;
    const focusable = panel.current.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], summary, select, input, [tabindex="0"]');
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

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60" onClick={onClose}>
      <div ref={panel} role="dialog" aria-modal="true" aria-label={title} onKeyDown={trapTab}
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full max-w-md flex-col border-l border-line bg-panel shadow-2xl">
        <header className="flex items-center justify-between gap-3 border-b border-line p-4">
          <h2 className="font-display text-xl text-gold-soft">{title}</h2>
          <button ref={close} type="button" onClick={onClose}
            className="min-h-10 rounded border border-line px-3 text-sm text-muted hover:text-text">
            Close <span className="sr-only">(Escape)</span>
          </button>
        </header>
        <div className="flex-1 overflow-auto p-4">{children}</div>
      </div>
    </div>
  );
}
