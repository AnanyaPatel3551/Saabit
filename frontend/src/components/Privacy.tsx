import { Logo } from "./Logo";

const GROQ_POLICY = "https://groq.com/privacy-policy/";
const NVIDIA_POLICY = "https://www.nvidia.com/en-us/about-nvidia/privacy-policy/";

/** What happens to your data, in plain words. Kept in step with README "Privacy and data". */
export function Privacy() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-4 py-10">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <a href="/" aria-label="Saabit home"><Logo /></a>
        <a href="/" className="text-sm text-muted hover:text-text">Back to the app</a>
      </header>

      <h1 className="font-display text-3xl text-text">Privacy and data</h1>

      <section className="flex flex-col gap-2 text-sm leading-relaxed text-text">
        <h2 className="font-display text-xl text-gold-soft">Your file</h2>
        <p>
          Your file travels to the server over an encrypted connection (HTTPS) and is stored only
          on this server. It is deleted after 24 hours, or immediately when you choose "Delete
          my data now" in the workspace. Deleting removes the file, its cleaned copy and the
          evidence behind every answer.
        </p>
        <p>
          Each upload gets its own private key. Only your browser tab holds it (it is never put in
          a link), and the server keeps just a fingerprint of it, not the key itself. Without the
          key, nobody can read the file, its answers or its downloads through Saabit: the server
          answers as if the data did not exist. Closing the tab forgets the key, so to keep
          working on the file after that, upload it again.
        </p>
        <p>
          To answer repeated questions faster, Saabit keeps the plan of each question (which
          measure, grouping, filters and dates it asked for, not rows from your file) for up to
          7 days. "Delete my data now" does not remove these plans.
        </p>
        <p>
          There are no accounts and no analytics. The server keeps a technical log of each
          request (time, path, outcome, how long it took), never rows, cell values or your
          questions. There is no login: the private key above is what keeps an upload yours. The
          shared sample is public and has no key.
        </p>
      </section>

      <section className="flex flex-col gap-2 text-sm leading-relaxed text-text">
        <h2 className="font-display text-xl text-gold-soft">What the AI provider receives</h2>
        <p>
          Saabit uses an AI model from Groq, with NVIDIA as a backup, only to read your question
          and to phrase the answer. Every number is computed on this server by code.
        </p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            To understand a question, the model receives: the question, the kinds of columns
            your file has (such as state or category), the short lists of allowed values for
            columns that have few of them (for example state names), and the file's date range.
          </li>
          <li>
            To write the answer sentence, it receives the question and a table of totals that
            Saabit has already computed (at most 20 rows).
          </li>
          <li>It never receives raw rows from your file.</li>
        </ul>
        <p>
          What those providers do with the data they receive is set by their own policies:{" "}
          <a href={GROQ_POLICY} target="_blank" rel="noreferrer" className="text-gold hover:underline">
            Groq's privacy policy</a>{" "}and{" "}
          <a href={NVIDIA_POLICY} target="_blank" rel="noreferrer" className="text-gold hover:underline">
            NVIDIA's privacy policy</a>.
        </p>
      </section>

      <section className="flex flex-col gap-2 text-sm leading-relaxed text-text">
        <h2 className="font-display text-xl text-gold-soft">The sample data</h2>
        <p>
          "Try sample data" uses a public dataset that ships with the app, shared by every
          visitor, so it cannot be deleted. The evidence behind answers about it is kept on the
          server for 24 hours, like any other answer.
        </p>
      </section>
    </main>
  );
}
