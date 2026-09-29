import { useEffect, useState } from "react";

type HealthState =
  | { kind: "loading" }
  | { kind: "ok"; body: unknown }
  | { kind: "error"; message: string };

export default function App() {
  const [health, setHealth] = useState<HealthState>({ kind: "loading" });

  useEffect(() => {
    fetch("/api/health")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((body: unknown) => setHealth({ kind: "ok", body }))
      .catch((err: Error) => setHealth({ kind: "error", message: err.message }));
  }, []);

  return (
    <main className="mx-auto max-w-xl p-8 font-sans">
      <h1 className="text-4xl font-bold text-slate-900">Saabit</h1>
      <h2 className="mt-6 text-sm font-semibold uppercase tracking-wide text-slate-500">
        /api/health
      </h2>
      {health.kind === "loading" && <p className="mt-2 text-slate-600">Checking…</p>}
      {health.kind === "ok" && (
        <pre className="mt-2 rounded bg-slate-100 p-4 text-sm text-slate-800">
          {JSON.stringify(health.body, null, 2)}
        </pre>
      )}
      {health.kind === "error" && (
        <p className="mt-2 text-red-700">Backend not reachable: {health.message}</p>
      )}
    </main>
  );
}
