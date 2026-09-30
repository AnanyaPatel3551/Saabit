# Later

Ideas and known limits deliberately left out of the current phase. Each item says where it
came from and what would trigger doing it. Nothing here is being built right now.

## Accepted limits (decided, revisit if they start to hurt)

| Item | Why it is accepted | Revisit when |
| --- | --- | --- |
| **Sample build peaks at ~311 MB on Linux** (`python -m app.prepare_sample`, over the 300 MB runtime budget). The fix is two-pass streaming cleaning: pass 1 collects order IDs, status, row hashes and date statistics; pass 2 cleans block by block and appends to Parquet. | Runs only during `docker build` on the build machine, never on the 512 MB Render instance. `scripts/memcheck.py` gives this step its own 350 MB build budget. | Build step nears 350 MB, or a later phase needs cleaning at request time for large files. |
| **Cancelled rule is literal**: an order is cancelled only if a line's Status is exactly `Cancelled` (FR-3.3). Files that say `voided`, `canceled` or `refunded` show 0% cancellations. | Locked in Phase 1 to reproduce the deck's 14.3%; changing it changes the metric definition. | Second-file demo, or any non-Amazon file where cancellations matter. Needs a PRD decision. |
| **Ambiguous dates assume day-first** when every value fits both orders (e.g. all days ≤ 12). The assumption is written into the fix log. | Indian exports are mostly DD/MM; the Amazon file is unambiguous (month-first is proven by its values). | A US-format file with only early-month dates. |

## Data and cleaning

- **Two-digit years are read as 20xx** (`01-02-99` → 2099). Fine for current exports.
- **Unknown state spellings are kept exactly**, including stray spaces, so `"APO"` and `"APO "` are listed separately (FR-3.1 says keep as-is).
- **Malformed CSV rows** (wrong number of fields) are skipped by the cleaning loader and logged as `malformed_row`; the upload-time DuckDB count pads them instead. Totals still reconcile via `rows_in`.
- **XLSX row hashes use Python's `hash()`**, which differs between processes; only matters if hashes are ever compared across runs.
- **"8,597 repeated order IDs"** in the PRD is rows minus unique orders; 6,846 orders actually have more than one line. Settle the wording before an eval question uses it.
- **Golden anchor for a partly cancelled order**, once the second-file demo exists (the Amazon file never mixes cancelled and non-cancelled lines).

## Answers and evidence (from Phase 4)

- **Answer sentence**: `POST /run` returns `sentence: null` until the LLM writer and number checker exist (Phase 5, FR-7.1 to FR-7.3).
- **Chart on the evidence card** (FR-8.1) is frontend work; the card already holds the result rows a chart needs.
- **Upload memory headroom**: in the 512 MB container, `upload_25mb` and `confirm_25mb` peak at ~281 MB against the 300 MB budget. Each new module adds to the import baseline, so re-run `scripts/memcheck.py` in Docker after every phase.
- **Partial-month caveat on whole-data questions**: a question with no date range covers March 2022, so it carries the partial-month caveat even when the answer is a single total. Correct per FR-6.3, but it may read as noise in the UI.

## Storage and limits

- **24-hour expiry of dataset folders** (PRD, Storage). Must skip the sample cache, and must also remove evidence cards: cards for the sample are saved under `storage/<sample id>/cards/` and grow with every question.
- **Rate limits per IP**: 30 questions per 10 minutes, 5 uploads per hour (PRD, Abuse).

## API and deploy

- **`provider` field in `/api/health`** once the LLM client exists (PRD API table).
- **Split `requirements.txt`** into runtime and dev, so pytest and ruff are not in the image.
- **Frontend type check (`npm run build`) in CI.**
- **Render paid starter instance for judging week**, or ping before demos (free tier sleeps).

## Sample data licence

- Kaggle lists the licence as "Other (specified in description)" and the description names none; only credit is asked for (see `data/sample/README.md`). Confirm with the author, or switch to downloading at build time, **before the repo is public**.
