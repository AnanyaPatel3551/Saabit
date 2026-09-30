# Saabit — Product Requirements Document

Version: 29 Sep 2026

## TL;DR

Saabit is a web app where an Indian online seller uploads a sales export, asks questions in plain English, and gets answers in which every number is computed by code, checked two ways, and linked to its source rows. The AI only turns the question into a structured plan and phrases the result; it never produces a number.

The build window is 29 Sep to 1 Oct 2026, about 2.5 working days rather than the 4 days in the idea deck. This PRD therefore ships a verified core first and names exactly what gets cut if time runs out.

"Done" on 1 Oct means:

- A public URL where a judge can load the built-in sample or upload their own CSV/Excel file, with no login.
- The five headline answers from the deck reproduce exactly and show as Verified.
- `python eval.py` runs the golden question set and prints a score; GitHub Actions runs the tests on every push.
- A README with the architecture and eval results, a 2–3 minute demo video, and the updated deck.

Open question: the exact submission cut-off time on 1 Oct. Plan to submit at least 4 hours before it.

## Problem statement

Small Indian online sellers already have the data to run their business better, but no analyst to read it, and generic AI chatbots give confident numbers they cannot prove.

**Hackathon brief.** PS-04, AI Decision Engine for Business Data: turn raw business data into decisions a user can trust.

**Who has the problem.** Owners and operations managers of small sellers on Amazon, Flipkart, Shopify or their own D2C site. They export orders as CSV or Excel, make weekly calls on stock, fulfilment and ad spend, and have nobody to check the numbers. They are comfortable with spreadsheets, not SQL.

**What the data shows.** The demo file is the Amazon India Sale Report from Kaggle: 128,975 rows, 120,378 unique orders, 31 Mar to 29 Jun 2022. Every figure below was computed in both DuckDB and pandas.

| Finding | Value | Why a naive analysis gets it wrong |
| --- | --- | --- |
| Order-level cancellation | 14.3%, about 1 in 7; at least ₹69 lakh of order value | Counting rows instead of orders changes the rate |
| Merchant vs Amazon fulfilment | 17.5% (36,376 orders) vs 12.9% (84,002), 36% more often | Needs unique orders per fulfilment type |
| Revenue, non-cancelled | Apr ₹2.62 Cr, May ₹2.40 Cr, Jun ₹2.14 Cr; −16% per day, April to June | Cancelled rows still carry amounts; June ends on the 29th |
| State names | 69 spellings for 36 states and UTs | RJ, Rajsthan and Rajshthan are split three ways |
| Repeated order IDs | 8,597 | Multi-item orders double-count if rows are summed as orders |
| March | 171 rows only | A partial month looks like a collapse in a trend chart |
| Missing columns | No cost, no payment method | Profit and COD questions cannot be answered at all |

**Why existing tools fall short.**

- A chatbot with the file pasted in cannot hold 1.29 lakh rows in its context.
- A chatbot with code execution (ChatGPT or Claude with file upload) can compute, but it makes silent choices: rows vs orders, cancelled revenue in or out, which spellings count as one state. The user never sees those choices.
- Both will usually attempt a profit or COD answer instead of saying the file cannot answer it.
- BI tools (Power BI, Looker Studio) are accurate but need someone to model the data and build dashboards first.

**The gap Saabit fills:** plain-English questions, answers a non-analyst can verify, and an honest "this file cannot answer that".

Before the repo goes public: cite the Kaggle licence in the README, and if it does not allow redistribution, download the sample at build time instead of committing it.

## Goals, non-goals and success metrics

The one goal that matters: no wrong number is ever shown as Verified, and the judge can check any number in two clicks.

**Goals for 1 Oct**

1. **Trustworthy answers.** Every number is computed by code, run in two engines, and traceable to its rows.
2. **Transparent understanding.** The user sees and can edit how the question was read (metric, filters, dates, grouping).
3. **Honest limits.** On upload, the user sees what the file can and cannot answer; unanswerable questions are refused with the reason.
4. **Useful actions.** Recommendations cite evidence cards and are backtested on a held-out month.
5. **Works on other files.** A second, differently shaped sales file works after column confirmation.

**Non-goals (explicitly not building)**

- Login, accounts, teams, saved history across sessions.
- Marketplace API connectors (Amazon SP-API, Shopify API).
- Forecasting or ML models: three months of data is too little and would create false confidence.
- RAG or a vector database: the data is tabular and SQL is exact.
- Autonomous multi-step agents or fine-tuning.
- Free-form LLM-written SQL for questions outside the plan format. Those questions are refused for now (moved from the deck's fallback to post-hackathon).
- Files above 25 MB or 5 lakh rows.

**Success metrics**

| Metric | Target | How it is measured |
| --- | --- | --- |
| Golden questions answered correctly | ≥ 90% of 40 | `eval.py` compares to expected values computed independently |
| Unanswerable questions refused | 100% of 10 | `eval.py` checks plan status is `unsupported` with the right reason |
| Wrong answers marked Verified | 0 computation errors | Every golden answer where engines agree must also equal the expected value |
| Deck headline numbers reproduced | 5 of 5 exact | Pinned unit tests |
| Time to first answer on sample | < 60 s from landing page | Manual timing in the demo video |
| Answer latency | p50 < 4 s, p95 < 8 s | Timed in `eval.py` |
| Baseline comparison | Saabit beats a code-executing chatbot on correctness and refusals | Same 50 questions, both scores published |

Note on the Verified claim: two engines running the same plan catch computation bugs, not a misread question. Misreadings are caught by the user-visible plan and by the golden set. The deck now says "0 calculation errors marked Verified" and names this limit, which matches.

## Proposed solution

Saabit is an eight-step pipeline in which deterministic code does all computing and the language model does only two narrow jobs: translating a question into a validated JSON plan, and phrasing a result in one or two sentences.

**Core principles** (each maps to a feature a judge can see):

1. **AI plans, code computes.** No LLM output ever becomes a number. The plan is validated by Pydantic against a fixed list of metrics and columns before anything runs.
2. **Show the reading.** The plan appears as editable chips ("Cancellation rate · By fulfilment · Unique orders · Apr–Jun 2022"). Editing a chip re-runs without calling the LLM.
3. **Every number has a receipt.** Each answer carries an evidence card: chart, plan, generated SQL, pandas code, row count, source rows and caveats.
4. **Compute twice.** The plan is compiled independently to DuckDB SQL and to pandas. Matching results are marked Verified; a mismatch shows both values and no narrative.
5. **Refuse rather than guess.** Missing capability (no cost column) or an ambiguous question returns a refusal or a clarifying question, never a best guess.
6. **Recommendations are rules, not vibes.** Rules over evidence cards generate recommendations; the LLM only phrases them. Confidence comes from a backtest, not from the model.

**What the user experiences**

- Upload a file or click "Try sample data".
- Confirm detected columns in one click.
- See a data check: what the file can answer, what is missing, what was fixed.
- See 4–5 auto-insight cards without asking anything.
- Ask questions; get a one-line answer, a Verified badge, a chart and the evidence.
- See ranked recommendations, each citing its evidence card and backtest result.

## End-to-end flow

A judge goes from landing page to a verified answer in under a minute: sample data, one confirm click, one question.

**Screens**

| Screen | What is on it | Main action |
| --- | --- | --- |
| S1 Landing | One-line pitch, drop zone (CSV, XLSX, max 25 MB), "Try sample data" button, privacy note | Upload or load sample |
| S2 Confirm columns | Table of detected roles (date, order ID, amount, status, state, product, fulfilment, qty) with 3 sample values and a confidence tag; dropdown to change each; unmapped columns listed | Confirm |
| S3 Workspace, left | Data check: can answer (✓), cannot answer (✗ with reason), fixes applied (⚠ with count, expandable log) | Read, expand fixes |
| S3 Workspace, centre | Question box with 4 example chips; answer card: sentence, Verified badge, chart, "Understood as" plan chips | Ask, edit chips |
| S3 Workspace, right | Auto-insight cards (E1–E5) and ranked recommendations with evidence, backtest, confidence, estimated impact | Open evidence |
| S4 Evidence drawer | Tabs: Chart, Plan (JSON), SQL, pandas, Rows (paginated, CSV download), Caveats | Inspect, download |

**Flow, step by step**

1. User uploads a file or loads the sample. The raw file is stored unchanged.
2. Code detects column roles. If a required role (date, amount or order ID) is missing, S2 asks the user to pick it; nothing runs until confirmed.
3. Code cleans a copy: normalises states, parses dates, dedupes orders, flags partial months, marks cancelled orders. Each fix is logged.
4. Code builds the capability report and computes the auto-insight cards and recommendations in the background.
5. User asks a question. The LLM returns a plan with one of three statuses:
   1. `ok`: plan chips are shown and execution starts.
   2. `needs_clarification`: Saabit asks one question with 2–4 option chips ("Revenue by order date or ship date?").
   3. `unsupported`: a refusal card names the missing column and suggests the closest question it can answer.
6. Code validates the plan against the confirmed schema. Invalid plans are retried once with the error, then refused.
7. Code compiles the plan to SQL and to pandas and runs both.
8. Code compares results. Match within tolerance: Verified. Mismatch: an amber "Could not verify" card with both values; no sentence is written.
9. The LLM writes one or two sentences from the result table only. Code checks every number in the sentence against the result. If any number fails, a template sentence is used instead.
10. The answer card and evidence drawer render. The user can edit a plan chip, which re-runs steps 6 to 9 without the LLM planning step.

Question flow: every question ends in one of four outcomes.

```
User asks a question
  -> LLM returns a JSON plan (LLM step)
  -> Plan status?
       unclear      -> ask one question with 2-4 option chips -> user picks -> back to planning
       unsupported  -> refusal card naming the missing column
       ok           -> code validates the plan
                       -> run DuckDB SQL and pandas
                       -> engines agree?
                            no  -> "Could not verify": both values, no sentence
                            yes -> LLM writes 1-2 sentences (LLM step)
                                   -> every number matches the result?
                                        no  -> use template sentence -> Verified answer
                                        yes -> Verified answer (chart, SQL, rows, caveats)
```

The two LLM steps are each followed by a code check; only the path through all three checks reaches Verified.

## Functional requirements

Each pipeline step has a small set of testable requirements; P0 must ship on 1 Oct, P1 ships if time allows.

### Step 1 · Upload (code)

- **FR-1.1 (P0)** Accept CSV and XLSX up to 25 MB and 5 lakh rows; reject others with a clear message.
- **FR-1.2 (P0)** Detect encoding (UTF-8, then latin-1) and delimiter; read the first sheet of Excel files.
- **FR-1.3 (P0)** Store the raw file unchanged; all work happens on a cleaned copy stored as Parquet.
- **FR-1.4 (P0)** "Try sample data" loads the bundled Amazon file with roles pre-confirmed.

### Step 2 · Detect and confirm (code)

- **FR-2.1 (P0)** Score each column for each role using header synonyms plus value checks, for example: date parses for ≥ 95% of values; amount is numeric for ≥ 95%; order ID has high cardinality; status has ≤ 30 distinct values containing words like cancel or ship; state values match the state dictionary for ≥ 60%.
- **FR-2.2 (P0)** Only suggest a role at ≥ 0.8 confidence; below that, leave it blank for the user.
- **FR-2.3 (P0)** Required roles: date, amount, order ID. Optional: status, state, city, category, SKU, fulfilment, qty, channel.
- **FR-2.4 (P0)** The user can change any role; confirmed roles are the only schema the planner sees.

### Step 3 · Clean and capability check (code)

- **FR-3.1 (P0)** Normalise states with a dictionary of canonical names and known variants (RJ, Rajsthan, Rajshthan → Rajasthan); unknown values stay as-is and are listed.
- **FR-3.2 (P0)** Parse dates (the Amazon file uses MM-DD-YY); flag any month with fewer than 50% of the median month's days or rows as partial.
- **FR-3.3 (P0)** Mark an order cancelled using one fixed rule applied everywhere. Lock the rule to the one that produced 14.3% (all lines cancelled, or any line cancelled) and write it into the metric definitions.
- **FR-3.4 (P0)** Every fix writes a log entry: rule, column, before value, after value, row count. The log is shown and downloadable.
- **FR-3.5 (P0)** Capability report derived from roles: for example no cost column → profit and margin unsupported; no payment column → COD unsupported; no status → cancellation unsupported.

### Step 4 · Understand the question (AI)

- **FR-4.1 (P0)** The LLM receives only: confirmed schema, allowed metrics, allowed dimensions, distinct values for low-cardinality columns (≤ 50), date range, capability report. Never raw rows.
- **FR-4.2 (P0)** Output must validate against the plan schema below; temperature 0; JSON mode.
- **FR-4.3 (P0)** One retry with the validation error; second failure → polite refusal.
- **FR-4.4 (P0)** Filter values are snapped to real values ("rajasthan" → Rajasthan) by code, not trusted from the LLM.
- **FR-4.5 (P1)** Cache plans by normalised question text for demo speed and resilience.

Plan schema:

```json
{
  "status": "ok | needs_clarification | unsupported",
  "metric": "revenue | orders | units | aov | cancellation_rate",
  "group_by": ["month | week | state | city | category | sku | fulfilment | channel"],
  "filters": [{"column": "state", "op": "in | not_in | eq", "values": ["Rajasthan"]}],
  "date_range": {"start": "2022-04-01", "end": "2022-06-30"},
  "sort": {"by": "value", "dir": "desc"},
  "limit": 10,
  "clarification": {"question": "...", "options": ["..."]},
  "unsupported_reason": "..."
}
```

Metric definitions (fixed in code, identical in SQL and pandas):

| Metric | Definition |
| --- | --- |
| revenue | Sum of amount over order lines whose order is not cancelled |
| orders | Count of distinct order IDs |
| units | Sum of qty over non-cancelled orders |
| aov | revenue ÷ count of distinct non-cancelled orders |
| cancellation\_rate | Distinct cancelled orders ÷ distinct orders, as % |

### Step 5 · Compute twice (code)

- **FR-5.1 (P0)** `compile_sql(plan)` builds SQL with sqlglot's builder (not string formatting) against a DuckDB view of the cleaned Parquet.
- **FR-5.2 (P0)** `compile_pandas(plan)` is written separately, with no shared helper that computes the metric.
- **FR-5.3 (P0)** DuckDB connection is read-only, 10 s timeout, result capped at 500 rows.

### Step 6 · Verify (code)

- **FR-6.1 (P0)** Align both results on group keys; compare values with relative tolerance 1e-6 and absolute tolerance 0.01.
- **FR-6.2 (P0)** Verified only if keys match exactly and all values are within tolerance. Otherwise status Unverified, both results shown, no narrative.
- **FR-6.3 (P0)** Caveats are attached automatically: partial month in range, fixes applied to filtered columns, small sample (fewer than 30 orders in a group).

### Step 7 · Write the answer (AI + code)

- **FR-7.1 (P0)** The LLM gets the question, the plan and the result table (max 20 rows) and writes at most two sentences.
- **FR-7.2 (P0)** A number checker extracts every number (handles ₹, %, commas in Indian format, lakh, Cr) and each must match a result value, or a difference or ratio of two result values, after rounding. Any miss → template sentence.
- **FR-7.3 (P0)** Template sentences exist for every metric and grouping, so the app works with the LLM switched off.

### Step 8 · Evidence, insights and recommendations (AI + code)

- **FR-8.1 (P0)** Every answer produces an evidence card with ID, chart, plan, SQL, pandas code, row count, source rows (paginated, CSV download) and caveats.
- **FR-8.2 (P0)** Five auto-insight cards on load: E1 cancellation by fulfilment, overall and within each of the top 4 categories, E2 monthly revenue trend, E3 top states by orders, E4 top categories by revenue, E5 data fixes summary.
- **FR-8.3 (P0)** Recommendations come from rules over insight cards, for example: if one fulfilment type's cancellation rate exceeds another's by ≥ 3 points in the training months, and the gap keeps its sign within each of the top 4 categories, recommend testing a move of its top SKUs by cancelled orders. Each cites its card IDs.
- **FR-8.4 (P1)** Backtest: compute each rule on Apr–May, then check the same gap in June only. Confidence: High if the gap keeps its sign and stays ≥ 3 points in June with ≥ 1,000 orders per group; Medium if it keeps its sign; Low otherwise.
- **FR-8.5 (P1)** Estimated impact shows its formula and its assumption, and a caveat that the within-category check reduces, but does not rule out, other causes such as courier, region or SKU mix inside a category.

Slide 6 of the deck already shows these outputs: Apr–May 17.6% vs 12.9%, held-out June 17.46% vs 12.87%, gap holding in each top-4 category. The built app must reproduce them exactly, so they join the pinned tests.

## System architecture

One FastAPI service serves both the API and the built React app, so there is one URL, one deploy and no CORS; the LLM is an external call that sits behind a validation wall.

```
React app (upload, ask, inspect)
   | /api
FastAPI service (one Render deploy)
   Ingest and detect roles
   Clean and capability check
   Validate the plan (Pydantic)  <-> LLM provider (Groq GPT-OSS 120B)  [plan]
   DuckDB via SQL  |  pandas      (two independent engines)
   Verify: engines agree -> Verified
   Answer text + number check    <-> LLM provider  [text]
   Evidence cards and recommendations
Storage: raw file, Parquet, metadata; 24 h expiry
```

The LLM touches the pipeline at two points only, planning and phrasing, and both outputs are checked by code before anyone sees them.

**Stack**

| Layer | Choice | Notes |
| --- | --- | --- |
| Frontend | React + Vite + Tailwind, Recharts for charts | Built to static files, served by FastAPI |
| API | FastAPI, Pydantic v2 | Async endpoints; heavy work in a thread pool |
| Compute A | DuckDB over Parquet | Read-only connection, SQL built with sqlglot |
| Compute B | pandas | Independent implementation of each metric |
| LLM | GPT-OSS 120B on Groq (`openai/gpt-oss-120b`), temperature 0, low reasoning effort, JSON mode | Replaces Llama 3.3 70B (`llama-3.3-70b-versatile`), which Groq retired on 16 Aug 2026. NIM fallback was cut; templates if Groq is unavailable |
| Storage | Per-dataset folder on local disk: raw file, cleaned Parquet, metadata JSON | Deleted after 24 hours; sample dataset preloaded at startup |
| Tests and CI | pytest, GitHub Actions | Unit tests + golden-number tests on every push |
| Hosting | Render web service from a Dockerfile | Health check at `/api/health` |

**Data model.** After confirmation, every file is mapped to one canonical table, so the planner, compilers and tests only ever see these names.

| Canonical column | Type | Amazon file source |
| --- | --- | --- |
| order\_id | text | Order ID |
| order\_date | date | Date |
| status\_raw | text | Status |
| is\_cancelled | bool | Derived from Status (rule in FR-3.3) |
| amount | decimal (₹) | Amount |
| qty | int | Qty |
| state | text (cleaned) | ship-state |
| city | text | ship-city |
| category | text | Category |
| sku | text | SKU |
| fulfilment | text | Fulfilment (Amazon, Merchant) |
| channel | text | Sales Channel |

Other entities, held as JSON per dataset: `Dataset` (id, filename, rows, roles, created\_at), `FixLog` entries, `CapabilityReport`, `EvidenceCard` (id, question, plan, sql, pandas\_code, result, verified, caveats), `Recommendation` (id, text, cites, backtest, confidence, impact).

**API**

| Method and path | Purpose | Returns |
| --- | --- | --- |
| POST /api/datasets | Upload file | dataset\_id, detected roles with confidence |
| POST /api/datasets/sample | Load bundled sample | dataset\_id, roles already confirmed |
| POST /api/datasets/{id}/confirm | Confirm roles, run cleaning | capability report, fix log summary |
| GET /api/datasets/{id}/overview | Data check, insight cards, recommendations | the three left and right panels |
| POST /api/datasets/{id}/plan | Question → plan | plan with status |
| POST /api/datasets/{id}/run | Plan → answer | sentence, verified flag, evidence card |
| GET /api/cards/{card\_id}/rows | Source rows | paginated rows; `?format=csv` for download |
| GET /api/datasets/{id}/fixes | Full fix log | CSV |
| GET /api/health | Liveness and LLM provider status | ok, provider |

Splitting `plan` and `run` is deliberate: editing a chip calls only `run`, and the eval can test planning and computing separately.

**Repository layout**

```
Saabit/
  backend/app/
    main.py            # FastAPI app, static files, routes
    api/               # route handlers, request/response models
    core/
      ingest.py        # read CSV/XLSX, encoding, Parquet
      detect.py        # role scoring
      clean.py         # states, dates, dedupe, cancelled flag, fix log
      capability.py    # what the file can answer
      metrics.py       # metric definitions (single source of truth)
      plan.py          # Pydantic plan schema + validation + value snapping
      compile_sql.py   # plan -> sqlglot -> DuckDB
      compile_pandas.py# plan -> pandas (independent)
      verify.py        # compare results, caveats
      narrate.py       # LLM sentence + templates
      numcheck.py      # number extraction and matching
      insights.py      # E1-E5 cards
      recommend.py     # rules, backtest, confidence
    llm/client.py      # Groq, NIM fallback, retries, timeouts
    llm/prompts.py
    data/states.json   # canonical states and variants
  backend/tests/
  frontend/
  eval/golden.yaml, eval/questions.yaml, eval/answer_key/, eval/eval.py, eval/baseline/
  notebooks/golden_answers.ipynb
  data/sample/
  Dockerfile, render.yaml, .github/workflows/ci.yml, README.md
```

The question flow, with every branch, is drawn in the End-to-end flow section.

## Design decisions

Every decision below trades capability for trust or for shipping on time; each is a ready answer to "why didn't you just…?" in the judging and the interview.

| # | Decision | Chosen | Rejected | Why |
| --- | --- | --- | --- | --- |
| D1 | Who computes numbers | Code only | LLM with code interpreter | LLM-written code makes silent choices; fixed metric code can be unit-tested |
| D2 | Question format | Structured JSON plan | Free text-to-SQL | A plan is small, validatable, shown to the user and editable; free SQL is none of these |
| D3 | Verification | Two independent engines on one plan | Single engine; LLM self-check | Catches compiler and cleaning bugs cheaply. Limit: a misread question passes both, so the plan is shown to the user |
| D4 | Column detection | Rules + user confirmation | LLM guesses roles | Rules are predictable and testable; the LLM can be confidently wrong about a column |
| D5 | Cleaning | Dictionary + logged, reversible fixes | Fuzzy matching or LLM normalisation | Every change is explainable row by row; fuzzy matching can merge different places |
| D6 | LLM input | Schema, allowed values, aggregates | Raw rows | Privacy, token cost, and it removes the temptation for the model to calculate |
| D7 | Answer text | LLM sentence + number check, template fallback | Unchecked LLM text | A single hallucinated number would break the whole promise |
| D8 | Recommendations | Rules over evidence + backtest | LLM brainstorming | Every recommendation is traceable and its confidence is earned, not asserted |
| D9 | Model | GPT-OSS 120B on Groq | GPT-4-class paid APIs | Free tier, fast, good at JSON; the plan format keeps the task within its reach. Llama 3.3 70B was the original choice until Groq retired it on 16 Aug 2026 |
| D10 | Out-of-format questions | Refuse with nearest supported question | Free-form SQL fallback | Not enough time to make free SQL safe and verified; refusal keeps the zero-error promise |
| D11 | Deployment | One service, one Dockerfile | Separate frontend and backend hosts | One URL, no CORS, one thing to break |
| D12 | Storage | Local files, 24-hour expiry | Database, S3 | No accounts means no need for persistence; less to secure |
| D13 | Forecasting | None | Prophet or ARIMA | Three months cannot support a forecast honestly |
| D14 | Causal claims | Shown as associations, checked within the top 4 categories, with a caveat | "Moving SKUs will cut cancellations by X" | The within-category check removes the most obvious confounder; other causes remain, and saying so is a credibility gain |

## Evaluation plan

One command, `python eval.py`, runs 50 questions end to end and prints a scorecard; the same file drives CI and the README results table.

**Golden set composition**

| Group | Count | Examples | What it proves |
| --- | --- | --- | --- |
| Single metric | 12 | Revenue in May 2022; orders in June 2022 | Metric definitions are right |
| Breakdowns | 10 | Top 5 states by orders; revenue by category | Grouping, sorting, cleaned dimensions |
| Trends and comparisons | 8 | Monthly revenue Apr to Jun; cancellation Amazon vs Merchant | Date handling, partial months |
| Trap questions | 10 | Cancellation rate in Rajasthan; orders in March | Cleaning, dedupe, partial-month caveat |
| Unanswerable | 10 | Profit margin by category; COD share; next month's sales | Correct refusal and reason |

**Pinned expected answers** (from the deck; computed independently of Saabit's code):

| Question | Expected | Must also |
| --- | --- | --- |
| Revenue in May 2022 | ₹2,39,53,534 | Exclude cancelled orders |
| Orders in June 2022 | 35,141 | Count unique order IDs |
| Cancellation rate in Rajasthan | 14.2% of 2,512 orders | Merge RJ, Rajsthan, Rajshthan |
| State with the most orders | Maharashtra, 20,780 | Clean state names first |
| Profit margin by category | Refuse | Say there is no cost column |

**Rules for the golden set**

- Expected values are computed once with plain pandas in a separate notebook and answer-key script that never import the app, reviewed by hand, and frozen in `eval/golden.yaml` (anchors) and `eval/questions.yaml` (the 50 questions). Saabit's own code never generates them.
- About 15 questions are phrased the way a seller would type them, including Hinglish and typos ("rajsthan ka cancellation kitna hai"), so the set is not written to suit the planner.
- Each entry records: question, expected status, expected value(s), tolerance, required caveat.

**Scorecard printed by `eval.py`**

- Accuracy on answerable questions, refusal rate on unanswerable ones.
- Count of Verified answers that do not match expected (must be 0).
- Plan failures vs compute failures, listed separately.
- p50 and p95 latency.

**Other tests**

- Robustness: the same file with the cost, status or state column removed must produce the matching "not available" messages.
- Planted anomalies: inject a 3x revenue spike in one state-week; E-cards must surface it.
- Second file: one differently shaped sales CSV (different headers, DD/MM/YYYY dates) runs 10 questions after confirmation.
- CI: unit tests and the pinned five run on every push; the full LLM eval runs manually or nightly to protect the free-tier rate limit.

**Baseline.** Run the same 50 questions through ChatGPT or Claude with the file uploaded and code execution on, one fresh chat per question, scored by the same rubric. Publish both scorecards with failures. Do not use "CSV pasted into a chat": 1.29 lakh rows do not fit, so judges would read it as an unfair comparison.

## Production readiness

For this build, "production ready" means a stranger can use the public URL with their own file and nothing breaks, leaks or lies; it does not mean multi-tenant scale.

| Area | Requirement |
| --- | --- |
| Reliability | Every endpoint returns a typed error with a user-readable message; no stack traces reach the UI. LLM calls: 15 s timeout, 1 retry, then NIM, then template mode |
| Degraded mode | With no LLM available, the data check, insight cards, recommendations and chip-edited questions still work; a banner says typed questions are paused |
| Security | Upload: extension and content sniffing, 25 MB limit, no macros executed, filenames never used as paths. DuckDB read-only, sqlglot-built queries only. API keys in environment variables, never in the repo |
| Prompt injection | Cell values reach the LLM only as the distinct values of low-cardinality columns, truncated to 60 characters; the plan schema cannot express anything outside allowed metrics and columns |
| Privacy | Raw rows never sent to the LLM; datasets deleted after 24 hours; privacy note on the landing page |
| Abuse | Rate limit per IP: 30 questions per 10 minutes, 5 uploads per hour |
| Performance | Sample load < 5 s; question to answer p95 < 8 s; memory under 512 MB for the sample |
| Observability | Structured JSON logs per request with dataset id, plan, verified flag, latency and LLM provider; no row data in logs |
| Hosting | Render with a health check. The free tier sleeps after inactivity, so either use the paid starter instance for judging week or ping the URL before any demo |
| Accessibility | Keyboard navigable, colour is never the only signal (Verified has a text label), charts have a table view |
| Code quality | Type hints, ruff lint, tests in CI, README with architecture, decisions and eval results |

## Build plan, 29 Sep to 1 Oct

Backend correctness comes first because it is what makes Saabit different; the UI is built on day 2 against working endpoints, and day 3 is for proof and packaging, not new features.

**Tue 29 Sep: verified core, deployed by night**

- [ ] Repo, Dockerfile, CI, Render service with `/api/health` live (first hour)
- [ ] Ingest, role detection, confirm endpoint
- [ ] Cleaning: states dictionary, dates, cancelled rule, dedupe, fix log
- [ ] Metric definitions; plan schema; `compile_sql` and `compile_pandas`; verify
- [ ] Pinned tests: the five deck answers pass in both engines
- [ ] Capability report
- [ ] Deploy; hit `/run` with a hand-written plan on the live URL

**Wed 30 Sep: AI layer and the product**

- [ ] Groq client with NIM fallback; planner prompt; validation, retry, value snapping
- [ ] Answer writer, number checker, template sentences
- [ ] Insight cards E1–E5; recommendation rules; backtest on Apr–May vs June
- [ ] Frontend: landing, confirm columns, workspace three panels, evidence drawer
- [ ] Write `eval/questions.yaml` (50 questions) from the separate answer-key script
- [ ] Deploy; full flow works on the live URL

**Thu 1 Oct: prove it and ship it**

- [ ] Run `eval.py`, fix the top failures, freeze results
- [ ] Run the baseline, record both scorecards
- [ ] Second file demo (if time)
- [ ] README: pitch, screenshot, architecture, decisions, eval table, how to run
- [ ] Final deck: present tense, real eval scores, live URL and repo link; replace the 4-day plan slide with what shipped
- [ ] Record the 2–3 minute demo video on the live URL
- [ ] Submit at least 4 hours before the cut-off

**Cut order if behind** (cut from the top, never touch the verified core):

1. Second file demo
2. NIM fallback (keep templates)
3. Baseline run (state the method and publish later)
4. Backtest (show recommendations with confidence "not backtested")
5. Plan cache

**Risks**

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Groq rate limit or outage during demo or judging | Medium | Plan cache for demo questions, NIM fallback, template mode |
| Golden numbers disagree with the deck | Medium | Resolve on day 1 by fixing the cancelled-order rule; update the deck, not the tests |
| Frontend eats day 2 | High | One page, no router, Tailwind only; chips and cards before polish |
| Render cold start in front of a judge | High on free tier | Paid starter for the week or a ping before demo |
| Planner misreads Hinglish questions | Medium | Few-shot examples in the prompt; clarification status; editable chips |
| Scope creep | High | This PRD's non-goals list; new ideas go to a "later" section in the README |

## Winning the demo and the interview

Judges remember one moment, so the demo is built around a single contrast: the same question answered by a generic chatbot and by Saabit, where only Saabit's number is right and provable.

**Demo script, about 2.5 minutes**

1. **0:00 Hook (15 s).** "A seller asks: what's my cancellation rate in Rajasthan? A chatbot with code execution says X. The right answer is 14.2% of 2,512 orders. Here's why they differ, and how Saabit proves it." Use the real baseline result.
2. **0:15 Upload (20 s).** Try sample data, confirm columns in one click.
3. **0:35 Data check (20 s).** Point at the three warnings: 69 spellings merged, March partial, no cost column.
4. **0:55 Ask (40 s).** Ask the Rajasthan question in Hinglish. Show the plan chips, the Verified badge, then open Rows and show RJ, Rajsthan and Rajshthan merged.
5. **1:35 Refusal (15 s).** Ask for profit margin; show the refusal naming the missing cost column.
6. **1:50 Recommendation (25 s).** Open the fulfilment recommendation: the within-category evidence, the held-out June backtest, confidence, and the remaining caveat.
7. **2:15 Proof (15 s).** Terminal: `python eval.py` scorecard next to the baseline scorecard. End on "0 computation errors marked Verified".

**What a strong submission repo shows** (reviewers for a pre-placement interview read the repo, not just the demo):

- A README that opens with the scorecard and a screenshot, then the architecture diagram and the design-decision table from this PRD.
- Small, well-named modules with type hints, and tests that read like the spec (`test_rajasthan_variants_merge`, `test_cancelled_orders_excluded_from_revenue`).
- A commit history that shows steady progress over three days, not one giant commit.
- An honest "Limitations and next steps" section: shared-plan limit of double compute, no causal claims, three months of data, free-form questions refused.

**Interview questions to prepare for**

| Likely question | Short answer to have ready |
| --- | --- |
| Why not let the LLM write SQL? | It can, but you cannot validate or show intent; a plan is small, checked, visible and editable |
| What does computing twice actually catch? | Compiler, cleaning and aggregation bugs. Not misread questions; those are caught by the visible plan and the golden set |
| How do you stop hallucinated numbers in the text? | The number checker; any unmatched number falls back to a template |
| How would you scale this? | Postgres or a warehouse behind the same plan compiler, a job queue for cleaning, auth and per-tenant storage |
| What would you build next? | Guarded free-form SQL with a second independent query, marketplace connectors, cost upload for profit |
| What was the hardest bug? | Keep a real one from the build, with the test that now guards it |
