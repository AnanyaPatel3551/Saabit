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

## Planner and LLM (from Phase 5)

- **NVIDIA NIM fallback was cut** (PRD cut order, item 2). If Groq fails, `/plan` returns 503 `llm_unavailable`; data checks, insights and edited plans keep working.
- **Template mode for typed questions** when the LLM is down (PRD Reliability row: "then template mode").
- **Keep eval questions out of the few-shot examples.** `llm/prompts.py` uses "rajsthan ka cancellation kitna hai" as an example (as requested); if `eval/questions.yaml` uses the same wording, that question is no longer a fair test of the planner. Use different phrasings in the eval.
- **Plan cache is per process and in memory**: it empties on every restart or deploy, and each worker would have its own. Fine for one Render instance.

## Answer sentences (from Phase 6)

- **Sums and totals are not allowed numbers.** FR-7.2 allows result values, differences and ratios only, so a sentence like "together these states made ₹3.5 Cr" falls back to the template. Decide whether sums of shown rows should count.
- **The answer sentence is not stored on the evidence card.** `/run` returns it, but the saved card JSON has no `sentence`/`source`; add them if the UI needs to reload past answers.
- **Two LLM calls per typed question** (planner ~1,860 tokens + writer ~500): about 3 new questions a minute on the 8,000 TPM free tier. Edited chips pay only the writer call.
- **`cli ask --fake-answer` still plans with the real LLM**; it only fakes the writer. An offline way to test the checker by hand would need a `--plan` JSON option.

## Insights and recommendations (from Phase 7)

- **Wording check for "peak", "highest", "lowest", "rose", "fell"** in LLM answer sentences: the number checker passes correct numbers with wrong words ("peaked at ₹2.40 Cr in May" when April was higher). Enforce in code that a superlative sits next to the table's max/min.
- **Recommendation text is code-written, not LLM-phrased** (principle 6 allows the LLM to phrase). Exact but plain; phrasing could be added behind the number checker.
- **An overview can stay "computing" forever** if the server restarts while the background job runs. Add a started_at timeout (e.g. 10 minutes -> "failed", recompute on request).
- **R2 and R3 confidence is the weakest item's**: one category that recovers in June makes all of R3 "Low". Per-item confidence is already in `backtest`; the UI could show it.
- **Training months are assumed contiguous**: a partial month in the middle of the data would sit inside the training date range.
- **Ranked template wording** reads "Top 10 by orders" without naming the dimension ("states").

## Storage and limits

- **24-hour expiry of dataset folders** (PRD, Storage). Must skip the sample cache, and must also remove evidence cards: cards for the sample are saved under `storage/<sample id>/cards/` and grow with every question.
- **Rate limits per IP**: 30 questions per 10 minutes, 5 uploads per hour (PRD, Abuse).

## API and deploy

- **Split `requirements.txt`** into runtime and dev, so pytest and ruff are not in the image.
- **Render paid starter instance for judging week**, or ping before demos (free tier sleeps).

## Frontend (from Phase 8)

- **`GET /api/catalogue`** returning the metrics and dimensions this file supports (from `core/metrics.py`), so plan chips only offer what can be answered. Today the chips list every schema value and `/run` explains a bad choice.
- **Code-split Recharts** (`import()` the chart) to bring the 632 kB bundle under Vite's 500 kB warning.
- **Docker frontend stage on Node 22**: Vitest 5 and jsdom 30 ask for Node 22+; the image only builds (works on Node 20 with engine warnings), CI tests on Node 24.
- **Browser end-to-end test** (Playwright) for the full sample flow; Vitest covers components only.
- **Keep the dataset in the URL** so a refresh does not return to the landing page.
- **Clarification answers re-plan** as "question (option)"; a structured answer field in /plan would be cleaner.

## Eval (from Phase 9)

- **E6 "unusual state-weeks" insight and the planted-anomaly test** (cut for the deadline): flag state-weeks with revenue > 3x that state's median week and >= 30 orders; inject a 3x spike into a copy and assert E6 finds it. Needs week-aligned windows to stay under the 500-row result cap.
- **`eval.py --base-url`** to run against a deployed server. Blocked today because `/run` always calls the writer; needs a `write=false` option on `/run`.
- **Writer-inclusive latency** in the eval (the PRD's p50 < 4 s / p95 < 8 s is for the full answer); today's eval times plan + compute only.
- **Second-file demo** (PRD "Other tests"): one differently shaped CSV, 10 questions.
- **Ambiguous place names** ("New Delhi" is a city and a state spelling): the planner picks one silently (eval x07). Offer a clarification when a value matches both a city and a state.
- **City spellings beyond case and spaces** (Bangalore vs Bengaluru, Gurgaon vs Gurugram) would need a city dictionary like states.json.
- **Detection: other look-alike status columns** (payment status, refund status are now excluded from the status role; review other roles for similar traps, e.g. "billing state").

## LLM providers and tokens (from Phase 9 close-out)

- **NIM latency is uneven** (single calls from 2 s to over 15 s on the trial endpoint): consider a longer timeout for the fallback provider only, or a third provider.
- **Warm the plan cache at image build** for the example chips and demo questions, so the demo never waits on a model.
- **Plan cache expiry**: files under `storage/plan_cache` are never deleted; fold them into the 24-hour expiry job.
- **Share the cool-down across workers**: it is in-process memory today (one worker on Render, so fine for now).

## Sample data licence

- Kaggle lists the licence as "Other (specified in description)" and the description names none; only credit is asked for (see `data/sample/README.md`). Confirm with the author, or switch to downloading at build time, **before the repo is public**.
