import { useRef, useState, type DragEvent } from "react";
import { loadSample, uploadDataset } from "../api/client";
import type { Dataset } from "../api/types";

const MAX_BYTES = 25 * 1024 * 1024;

/** Quick checks before upload; the server repeats them (FR-1.1, FR-1.2). */
export function fileProblem(file: File): string | null {
  if (!/\.(csv|xlsx)$/i.test(file.name)) return "Please choose a .csv or .xlsx file.";
  if (file.size > MAX_BYTES) return "The file is larger than 25 MB.";
  return null;
}

/** S1: pitch, drop zone, sample button and privacy note. Owns upload and sample calls. */
export function Landing({ onDataset }: { onDataset: (dataset: Dataset) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  async function start(label: string, call: () => Promise<Dataset>) {
    setBusy(label);
    setError(null);
    try {
      onDataset(await call());
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  function upload(file: File | undefined) {
    if (!file) return;
    const problem = fileProblem(file);
    if (problem) return setError(problem);
    void start(`Reading ${file.name}…`, () => uploadDataset(file));
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    upload(event.dataTransfer.files[0]);
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-8 px-4 py-12">
      <header>
        <p className="mb-2 text-sm uppercase tracking-[0.3em] text-gold">Saabit</p>
        <h1 className="font-display text-4xl leading-tight text-text sm:text-5xl">
          Ask your sales data anything.<br />
          <span className="text-gold-soft">Every number checked twice.</span>
        </h1>
        <p className="mt-4 text-muted">
          Upload your orders file and ask in English or Hinglish. Each answer is computed by code,
          checked by two separate engines, and linked to the rows behind it.
        </p>
      </header>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`flex flex-col items-center gap-3 rounded-2xl border-2 border-dashed p-10 text-center transition-colors ${
          dragging ? "border-gold bg-gold/5" : "border-line bg-panel"}`}
      >
        <p className="text-text">Drop a CSV or XLSX file here</p>
        <p className="text-xs text-muted">Up to 25 MB</p>
        <input ref={input} id="file" type="file" accept=".csv,.xlsx" className="sr-only"
          onChange={(e) => upload(e.target.files?.[0])} disabled={busy !== null} />
        <label htmlFor="file" tabIndex={0} role="button"
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.current?.click(); } }}
          className="cursor-pointer rounded-lg border border-gold/60 px-4 py-2 text-gold-soft hover:bg-gold/10">
          Choose a file
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <button type="button" disabled={busy !== null}
          onClick={() => void start("Loading the sample…", loadSample)}
          className="rounded-lg bg-gold px-5 py-2.5 font-medium text-ink hover:bg-gold-soft disabled:opacity-50">
          Try sample data
        </button>
        <span className="text-sm text-muted">Amazon India sales, Apr–Jun 2022</span>
      </div>

      {busy && <p role="status" className="text-sm text-muted">{busy}</p>}
      {error && <p role="alert" className="rounded-lg border border-bad/60 bg-bad/10 p-3 text-sm">{error}</p>}

      <p className="border-t border-line pt-4 text-xs text-muted">
        Privacy: your rows never leave this server. The language model only sees column names,
        allowed values and totals computed by code, never raw rows. No account is needed.
      </p>
    </main>
  );
}
