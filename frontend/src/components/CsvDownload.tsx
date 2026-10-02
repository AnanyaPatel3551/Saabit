import { useState } from "react";

/** A download that needs the dataset's access key, so it is a button that fetches the file,
 * not a plain link (a link cannot send the key header). */
export function CsvDownload({ label, download, className }: {
  label: string;
  download: () => Promise<void>;
  className: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await download();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The download failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button type="button" onClick={() => void save()} disabled={busy}
        className={`${className} cursor-pointer bg-transparent p-0 text-left disabled:cursor-wait`}>
        {label}
      </button>
      {error && <span role="alert" className="ml-2 text-xs text-bad">{error}</span>}
    </>
  );
}
