import { useRef, useState, type DragEvent } from "react";
import { loadSample, loadShopifySample, uploadDataset } from "../api/client";
import type { Dataset } from "../api/types";
import { LandingPreview } from "./LandingPreview";
import { Logo } from "./Logo";
import { ProofStrip } from "./ProofStrip";

const REPO_URL = "https://github.com/AnanyaPatel3551/Saabit";
const KAGGLE_URL = "https://www.kaggle.com/datasets/thedevastator/unlock-profits-with-e-commerce-sales-data";
const LICENCE_URL = `${REPO_URL}/blob/main/data/sample/README.md`;
const STEPS = ["Upload your orders", "Ask in plain English or Hinglish",
               "See the number, the check, and the rows behind it"];

const MAX_BYTES = 25 * 1024 * 1024;

/** Quick checks before upload; the server repeats them (FR-1.1, FR-1.2). */
export function fileProblem(file: File): string | null {
  if (!/\.(csv|xlsx)$/i.test(file.name)) return "Please choose a .csv or .xlsx file.";
  if (file.size > MAX_BYTES) return "The file is larger than 25 MB.";
  return null;
}

/** S1: hero and actions beside an example answer, then the proof, the sample and a footer. */
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
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-10 px-4 py-10">
      <Logo size={36} wordClass="text-2xl" />

      <div className="grid items-start gap-10 lg:grid-cols-2">
        <div className="flex flex-col gap-6">
          <h1 className="font-display text-4xl leading-tight text-text sm:text-5xl">
            <span className="hero-line block">Ask your sales data anything.</span>
            <span className="hero-line hero-line-2 block text-gold-soft">Every number checked twice.</span>
          </h1>
          <p className="hero-line hero-line-3 text-lg text-text">
            An AI analyst that proves every number it gives you.
          </p>
          <p className="text-muted">
            Upload your orders file and ask in English or Hinglish. Each answer is computed by code,
            checked by two separate engines, and linked to the rows behind it.
          </p>

          <ol className="grid gap-2 sm:grid-cols-3" aria-label="How it works">
            {STEPS.map((step, i) => (
              <li key={step} className="flex gap-2 rounded-xl border border-line bg-panel p-3 text-sm text-text">
                <span className="font-display text-xl leading-none text-gold" aria-hidden="true">{i + 1}</span>
                <span><span className="sr-only">Step {i + 1}: </span>{step}</span>
              </li>
            ))}
          </ol>

          <div className="flex flex-wrap items-center gap-4">
            <button type="button" disabled={busy !== null}
              onClick={() => void start("Loading the sample…", loadSample)}
              className="min-h-11 rounded-lg bg-gold px-5 py-2.5 font-medium text-ink hover:bg-gold-soft disabled:opacity-50">
              Try sample data
            </button>
            <button type="button" disabled={busy !== null}
              onClick={() => void start("Loading the Shopify-style file…", loadShopifySample)}
              className="min-h-11 text-sm text-gold-soft underline-offset-4 hover:underline disabled:opacity-50">
              Try a different file format (synthetic)
            </button>
          </div>

          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`flex flex-col items-center gap-2 rounded-2xl border-2 border-dashed p-6 text-center transition-colors ${
              dragging ? "border-gold bg-gold/5" : "border-line bg-panel"}`}
          >
            <p className="text-text">Or drop your own CSV or XLSX file here</p>
            <p className="text-xs text-muted">Up to 25 MB</p>
            <input ref={input} id="file" type="file" accept=".csv,.xlsx" className="sr-only"
              onChange={(e) => upload(e.target.files?.[0])} disabled={busy !== null} />
            <label htmlFor="file" tabIndex={0} role="button"
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.current?.click(); } }}
              className="min-h-10 cursor-pointer rounded-lg border border-gold/60 px-4 py-2 text-gold-soft hover:bg-gold/10">
              Choose a file
            </label>
          </div>

          {busy && <p role="status" className="text-sm text-muted">{busy}</p>}
          {error && <p role="alert" className="rounded-lg border border-bad/60 bg-bad/10 p-3 text-sm">{error}</p>}
        </div>

        <LandingPreview />
      </div>

      <ProofStrip />

      <section aria-labelledby="sample-heading" className="rounded-xl border border-line bg-panel p-4">
        <h2 id="sample-heading" className="mb-2 font-display text-lg text-text">The sample data</h2>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
          <div><dt className="text-xs text-muted">Dataset</dt>
            <dd className="text-text">Amazon India sales report</dd></div>
          <div><dt className="text-xs text-muted">Dates</dt>
            <dd className="text-text">31 Mar to 29 Jun 2022</dd></div>
          <div><dt className="text-xs text-muted">Rows</dt><dd className="text-text">1,28,975</dd></div>
          <div><dt className="text-xs text-muted">Orders</dt><dd className="text-text">1,20,378</dd></div>
        </dl>
        <p className="mt-3 text-xs text-muted">
          "E-Commerce Sales Dataset" by ANil (data.world/anilsharma87), published on Kaggle by The
          Devastator.{" "}
          <a href={KAGGLE_URL} target="_blank" rel="noreferrer" className="text-gold hover:underline">Source</a>
          {" · "}
          <a href={LICENCE_URL} target="_blank" rel="noreferrer" className="text-gold hover:underline">Licence note</a>
        </p>
      </section>

      <p className="text-xs text-muted">
        Privacy: your rows never leave this server. The language model only sees column names,
        allowed values and totals computed by code, never raw rows. No account is needed, and
        uploads are deleted after 24 hours.
      </p>

      <footer className="flex flex-wrap items-center gap-4 border-t border-line pt-6 text-sm">
        <a href={REPO_URL} target="_blank" rel="noreferrer"
          className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-line px-4 text-text hover:border-gold/60">
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" className="fill-current">
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
          </svg>
          View source on GitHub
        </a>
        <a href="/how-we-test" className="text-gold underline-offset-4 hover:underline">How we test</a>
      </footer>
    </main>
  );
}
