import { useState } from "react";
import { confirmRoles } from "../api/client";
import type { DataCheck, Dataset, Role } from "../api/types";
import { REQUIRED_ROLES, ROLES, humanize } from "../lib/plan";
import { isSynthetic } from "./DatasetChip";

function confidenceTag(confidence: number): string {
  if (confidence >= 0.8) return "High";
  if (confidence >= 0.5) return "Medium";
  return "Low";
}

/** S2: check the detected role for each column; required roles block Confirm (FR-2). */
export function ConfirmColumns({ dataset, onConfirmed, onBack }: {
  dataset: Dataset;
  onConfirmed: (check: DataCheck) => void;
  onBack: () => void;
}) {
  const detected = new Map(dataset.roles.map((r) => [r.role, r]));
  const [choice, setChoice] = useState<Record<string, string | null>>(
    Object.fromEntries(ROLES.map((role) => [role, detected.get(role)?.column ?? null])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fixed = dataset.roles_confirmed;

  const missing = REQUIRED_ROLES.filter((role) => !choice[role]);
  const used = new Set(Object.values(choice).filter(Boolean));
  const unmapped = dataset.columns.filter((c) => !used.has(c));

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      onConfirmed(await confirmRoles(dataset.dataset_id, choice));
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-10">
      <button type="button" onClick={onBack} className="mb-4 text-sm text-muted hover:text-text">← Start over</button>
      <h1 className="font-display text-3xl text-text">Confirm your columns</h1>
      <p className="mt-3 text-text">
        We guessed what each column is. Change any that look wrong, then confirm.
      </p>
      <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted">
        <span>{dataset.filename} · {dataset.rows.toLocaleString("en-IN")} rows.</span>
        {isSynthetic(dataset) && (
          <span className="rounded border border-line px-1.5 py-0.5 text-xs">
            Synthetic data: made up to show a different file format
          </span>
        )}
        {fixed && <span>The sample's columns are fixed, so you only need to confirm.</span>}
      </p>

      <div className="mt-6 overflow-x-auto rounded-xl border border-line">
        <table className="w-full text-sm">
          <caption className="sr-only">Detected column for each role</caption>
          <thead className="bg-raised text-left text-muted">
            <tr>
              <th scope="col" className="px-3 py-2 font-normal">Role</th>
              <th scope="col" className="px-3 py-2 font-normal">Column</th>
              <th scope="col" className="px-3 py-2 font-normal">Sample values</th>
              <th scope="col" className="px-3 py-2 font-normal">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {ROLES.map((role: Role) => {
              const found = detected.get(role);
              const same = found?.column === choice[role];
              const required = REQUIRED_ROLES.includes(role);
              const tag = confidenceTag(found?.confidence ?? 0);
              return (
                <tr key={role} className="border-t border-line">
                  <th scope="row" className="px-3 py-2 text-left font-normal text-text">
                    {humanize(role)}
                    {required && <span className="ml-1 text-xs text-gold">(required)</span>}
                  </th>
                  <td className="px-3 py-2">
                    <label className="sr-only" htmlFor={`role-${role}`}>Column for {humanize(role)}</label>
                    <select id={`role-${role}`} value={choice[role] ?? ""} disabled={fixed}
                      onChange={(e) => setChoice({ ...choice, [role]: e.target.value || null })}
                      className={`w-full max-w-56 rounded border bg-raised px-2 py-1 text-text ${
                        required && !choice[role] ? "border-bad" : "border-line"}`}>
                      <option value="">Not in my file</option>
                      {dataset.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-2 text-muted">
                    {same && found?.samples.length ? found.samples.slice(0, 3).join(" · ") : "—"}
                  </td>
                  <td className="px-3 py-2">
                    {found?.column && same ? (
                      <span tabIndex={0} className="group relative inline-block rounded-full border border-line px-2 py-0.5 text-xs text-text">
                        {tag}
                        <span role="tooltip"
                          className="pointer-events-none absolute right-0 top-full z-10 mt-1 hidden w-64 rounded-lg border border-line bg-raised p-2 text-left text-xs text-muted shadow-lg group-hover:block group-focus:block">
                          {found.reasons.join("; ") || "No reasons recorded."}
                        </span>
                      </span>
                    ) : <span className="text-xs text-muted">{choice[role] ? "Your choice" : "—"}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-sm text-muted">
        Not used: {unmapped.length ? unmapped.join(", ") : "every column is used"}.
      </p>

      {missing.length > 0 && (
        <p role="alert" className="mt-4 text-sm text-bad">
          Pick a column for {missing.map(humanize).join(", ")} to continue.
        </p>
      )}
      {error && <p role="alert" className="mt-4 rounded-lg border border-bad/60 bg-bad/10 p-3 text-sm">{error}</p>}

      <button type="button" onClick={() => void confirm()} disabled={busy || missing.length > 0}
        className="mt-6 rounded-lg bg-gold px-6 py-2.5 font-medium text-ink hover:bg-gold-soft disabled:opacity-50">
        {busy ? "Cleaning your data…" : "Confirm"}
      </button>
    </main>
  );
}
