import { useEffect, useRef, useState, type DragEvent } from "react";
import { getHealth, loadSample, loadShopifySample, uploadDataset } from "../api/client";
import type { Dataset } from "../api/types";
import { friendlyError } from "./ErrorNote";
import { Logo } from "./Logo";

/** After this long without a health reply, the free server is probably waking up. */
export const SLOW_HEALTH_MS = 2_000;

const REPO_URL = "https://github.com/AnanyaPatel3551/Saabit";
const STEPS = [
  { title: "Upload your orders", detail: "CSV or Excel, up to 25 MB" },
  { title: "Ask a question", detail: "In plain English or Hinglish" },
  { title: "See the proof", detail: "The number, the check, and the rows behind it" },
];

const MAX_BYTES = 25 * 1024 * 1024;

/** Quick checks before upload; the server repeats them (FR-1.1, FR-1.2). */
export function fileProblem(file: File): string | null {
  if (!/\.(csv|xlsx)$/i.test(file.name)) return "Please choose a .csv or .xlsx file.";
  if (file.size > MAX_BYTES) return "The file is larger than 25 MB.";
  return null;
}

/** S1: pitch, steps, drop zone, the two samples, privacy note and footer. */
export function Landing({ onDataset, notice }: {
  onDataset: (dataset: Dataset) => void;
  /** Why the last file could not be reopened (expired, or opened in another tab). */
  notice?: string;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [waking, setWaking] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let answered = false;
    const timer = setTimeout(() => { if (!answered) setWaking(true); }, SLOW_HEALTH_MS);
    getHealth().catch(() => undefined).finally(() => {
      answered = true;
      clearTimeout(timer);
      setWaking(false);
    });
    return () => clearTimeout(timer);
  }, []);

  async function start(label: string, call: () => Promise<Dataset>) {
    setBusy(label);
    setError(null);
    try {
      onDataset(await call());
    } catch (e) {
      setError(friendlyError(e).message);
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
    <main className="page-fade mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-8 px-4 py-12">
      {notice && (
        <p role="status" className="rounded-lg border border-amber/60 bg-amber/10 p-3 text-sm text-text">{notice}</p>
      )}
      {waking && (
        <p role="status" className="self-start rounded-full border border-line px-3 py-1 text-xs text-muted">
          Waking up the server… (~30s)
        </p>
      )}
      <header>
        <div className="mb-6">
          <Logo size={36} wordClass="text-2xl" />
        </div>
        <h1 className="font-display text-4xl leading-tight text-text sm:text-5xl">
          Ask your sales data anything.{" "}
          <span className="text-gold-soft">Every number checked twice.</span>
        </h1>
        <p className="mt-4 text-muted">
          Upload your orders file and ask in English or Hinglish. Each answer is computed by code,
          checked in two separate ways, and linked to the rows behind it.
        </p>
      </header>

      <ol className="grid items-stretch gap-3 sm:grid-cols-3" aria-label="How it works">
        {STEPS.map((step, i) => (
          <li key={step.title} className="flex h-full flex-col gap-1 rounded-xl border border-line bg-panel p-4">
            <p className="flex items-baseline gap-2">
              <span className="w-5 shrink-0 font-display text-2xl leading-none text-gold" aria-hidden="true">
                {i + 1}
              </span>
              <span className="font-medium text-text">
                <span className="sr-only">Step {i + 1}: </span>{step.title}
              </span>
            </p>
            <p className="pl-7 text-sm text-muted">{step.detail}</p>
          </li>
        ))}
      </ol>

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
      <button type="button" disabled={busy !== null}
        onClick={() => void start("Loading the Shopify-style file…", loadShopifySample)}
        className="-mt-4 self-start text-sm text-gold-soft underline-offset-4 hover:underline disabled:opacity-50">
        Try a different file format (synthetic Shopify-style orders)
      </button>

      {busy && <p role="status" className="text-sm text-muted">{busy}</p>}
      {error && <p role="alert" className="rounded-lg border border-bad/60 bg-bad/10 p-3 text-sm">{error}</p>}

      <p className="border-t border-line pt-4 text-xs text-muted">
        Privacy: files stay on this server and are deleted after 24 hours, or right away with
        "Delete my data now". Each upload gets a private key that only your browser holds. The
        AI sees your question, the kinds of columns, short lists of allowed values, the date range
        and totals worked out by code, never your rows. No accounts, no analytics.{" "}
        <a href="/privacy" className="text-gold hover:underline">Privacy and data</a>
      </p>

      <footer className="flex flex-col gap-2 text-xs text-muted sm:flex-row sm:flex-wrap sm:gap-x-6">
        <a href={REPO_URL} className="hover:text-text">Source on GitHub</a>
        <a href="/how-we-test" className="hover:text-text">How we test</a>
        <a href="/privacy" className="hover:text-text">Privacy</a>
        <span>
          Sample data: "E-Commerce Sales Dataset" by ANil (data.world/anilsharma87), published on
          Kaggle by The Devastator.
        </span>
      </footer>
    </main>
  );
}
