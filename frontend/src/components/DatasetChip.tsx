import { useEffect, useRef, useState } from "react";
import type { DataCheck, Dataset } from "../api/types";
import { dayLabel, indianDigits } from "../lib/format";

const SAMPLE_FILE = "amazon_sale_report.csv.gz";

export function isSynthetic(dataset: Dataset): boolean {
  return dataset.filename.toLowerCase().includes("synthetic");
}

/** Where a dataset came from, for the "About this data" popover. */
function about(dataset: Dataset): { title: string; lines: string[]; link?: [string, string] } {
  if (dataset.filename === SAMPLE_FILE) {
    return {
      title: "Amazon India sales report (sample)",
      lines: ['"E-Commerce Sales Dataset" by ANil (data.world/anilsharma87), published on Kaggle '
              + "by The Devastator.", "Loaded with its columns already confirmed."],
      link: ["Source on Kaggle",
             "https://www.kaggle.com/datasets/thedevastator/unlock-profits-with-e-commerce-sales-data"],
    };
  }
  if (isSynthetic(dataset)) {
    return { title: "Synthetic Shopify-style orders",
             lines: ["Made up by a script with a fixed seed to show a different file format. "
                     + "Not real sales data."] };
  }
  return { title: "Your upload",
           lines: ["Stored only on this server and deleted after 24 hours. Raw rows are never "
                   + "sent to the language model."] };
}

/** Dataset name, rows and dates; opens "About this data". Escape or a click outside closes it. */
export function DatasetChip({ dataset, check }: { dataset: Dataset; check: DataCheck }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const info = about(dataset);
  const dates = check.date_min && check.date_max
    ? `${dayLabel(check.date_min)} to ${dayLabel(check.date_max)}` : null;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const onClick = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  return (
    <div ref={box} className="relative min-w-0">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        aria-haspopup="dialog"
        className="flex min-h-10 max-w-full items-center gap-2 rounded-full border border-line bg-raised px-3 text-left text-xs">
        <span className="truncate text-text">{info.title}</span>
        <span className="hidden whitespace-nowrap text-muted sm:inline">
          · {indianDigits(check.rows_out)} rows{dates ? ` · ${dates}` : ""}
        </span>
        {isSynthetic(dataset) && <span className="rounded border border-line px-1 text-muted">Synthetic</span>}
      </button>
      {open && (
        <div role="dialog" aria-label="About this data"
          className="absolute left-0 top-full z-40 mt-2 w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-line bg-panel p-4 text-sm shadow-2xl">
          <h3 className="mb-2 font-display text-base text-gold-soft">About this data</h3>
          <dl className="mb-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
            <dt className="text-muted">File</dt><dd className="truncate text-text">{dataset.filename}</dd>
            <dt className="text-muted">Rows</dt><dd className="text-text">{indianDigits(check.rows_out)}</dd>
            {check.orders != null && (<><dt className="text-muted">Orders</dt>
              <dd className="text-text">{indianDigits(check.orders)}</dd></>)}
            {dates && (<><dt className="text-muted">Dates</dt><dd className="text-text">{dates}</dd></>)}
          </dl>
          {info.lines.map((line) => <p key={line} className="mb-1 text-xs text-muted">{line}</p>)}
          {info.link && (
            <a href={info.link[1]} target="_blank" rel="noreferrer"
              className="mt-2 inline-block text-xs text-gold hover:underline">{info.link[0]}</a>
          )}
        </div>
      )}
    </div>
  );
}
