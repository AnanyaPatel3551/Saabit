# Saabit

Ask questions about your sales file in plain English or Hinglish, and get numbers that are computed by code, checked by two independent engines, and linked to the rows behind them.

Live: https://saabit.onrender.com (free tier: the first request after a quiet spell can take about a minute while the service wakes up)

![Saabit workspace](docs/screenshots/workspace.png)

## Results

All numbers below come from `python eval/eval.py`. The 50 golden questions (40 answerable, 10 that should be refused) and the 15 anchors have expected values computed by a separate plain-pandas script that never imports the app (`eval/answer_key/questions.py`, `notebooks/golden_answers.ipynb`). Runs are made with `--no-cache`, so every question goes to the model.

| Measure | Saabit, Groq `openai/gpt-oss-120b` (final run) | Saabit, NIM `nvidia/nemotron-3-super-120b-a12b` | Baseline (code-executing chatbot) |
| --- | --- | --- | --- |
| Answerable questions correct | _to be filled_ | 38/40 (95%) | _to be filled_ |
| Unanswerable questions refused | _to be filled_ | 10/10 (100%) | _to be filled_ |
| Wrong answers marked Verified | _to be filled_ | 0 | not applicable |
| Golden anchors correct | _to be filled_ | 13/13 answerable, 2/2 refused | _to be filled_ |
| Latency p50 / p95 (plan and compute) | _to be filled_ | 3.9 s / 25.2 s | not measured |

The NIM run was made on 2 Oct 2026. Its two misses (x06 "Pondicherry revenue" and x07 "How many orders from New Delhi?") are both a place name read as a city instead of a state; see Limitations. "Wrong answers marked Verified" counts only calculation errors: answers the two engines agreed on that differ from the answer key.

The baseline uses the same questions and the same scoring rules (`eval/baseline/README.md`): ChatGPT or Claude with code execution on, the file uploaded, one fresh chat per question.

Time to see the numbers, measured end to end on the sample (`scripts/timing.py`). The answer sentence is written afterwards and fills in when it arrives.

| Question | Groq: numbers / sentence | NIM: numbers / sentence |
| --- | --- | --- |
| revenue by state in April 2022 | 1.9 s / 19.0 s | 3.2 s / 7.5 s |
| kurta ka cancellation rate in June | 1.8 s / 2.6 s | 8.6 s / 10.0 s |
| top 3 categories by orders in May 2022 | 1.6 s / 2.8 s | 3.5 s / 8.3 s |
| Top 5 states by revenue (pre-planned) | not measured | 0.9 s / 27.2 s |

## How it works

> Architecture diagram: to be added (`docs/img/architecture.png`)

1. **Upload**: a CSV or XLSX file up to 25 MB, stored unchanged; all work happens on a cleaned copy.
2. **Detect and confirm**: rules suggest which column is the date, amount, order ID and so on; the user confirms or changes them.
3. **Clean and check**: state names and city spellings are normalised, dates parsed, cancelled orders marked by one fixed rule, and every change written to a downloadable fix log. A capability report says what the file can and cannot answer.
4. **Plan**: the LLM turns the question into a small JSON plan (metric, grouping, filters, dates). Code validates it and snaps filter values to real values. The plan is shown to the user as editable chips.
5. **Compute twice**: the plan runs once as SQL in DuckDB (built with sqlglot) and once in pandas, written separately.
6. **Verify**: the two results are compared. Only a match (within rounding tolerance) is marked Verified; otherwise both values are shown and no sentence is written.
7. **Answer**: the numbers and chart appear at once. The LLM then writes one or two sentences, and every number in them must match the result, or a template sentence is used.
8. **Evidence and insights**: each answer has an evidence card (plan, SQL, pandas code, source rows, caveats). Five insight cards and rule-based recommendations, backtested on a held-out month, are computed when the file is confirmed.

![A Hinglish question answered with a Verified badge](docs/screenshots/answers.png)

A Hinglish question answered: 14.2% of 2,512 Rajasthan orders, Verified, with its caveats and the plan shown as editable chips.

![The evidence drawer showing the generated SQL](docs/screenshots/evidences.png)

The evidence drawer: the SQL that produced the number, next to the plan, the pandas code, the source rows and the caveats.

![A refusal with a suggested question](docs/screenshots/refusal.png)

A question the file cannot answer is refused with the reason and a nearby question it can answer.

![Ranked recommendations with backtest confidence](docs/screenshots/recommendation.png)

Recommendations: each one shows its backtest confidence, an estimated impact with the formula, and links to its evidence cards.

## Design decisions

From the PRD's decision table (`docs/PRD.md`, "Design decisions").

| Decision | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Who computes numbers | Code only | LLM with code interpreter | LLM-written code makes silent choices; fixed metric code can be unit-tested |
| Question format | Structured JSON plan | Free text-to-SQL | A plan is small, validatable, shown to the user and editable; free SQL is none of these |
| Verification | Two independent engines on one plan | Single engine; LLM self-check | Catches compiler and cleaning bugs cheaply. Limit: a misread question passes both, so the plan is shown to the user |
| Cleaning | Dictionary and logged, reversible fixes | Fuzzy matching or LLM normalisation | Every change is explainable row by row; fuzzy matching can merge different places |
| LLM input | Schema, allowed values, aggregates | Raw rows | Privacy, token cost, and it removes the temptation for the model to calculate |
| Answer text | LLM sentence with a number check, template fallback | Unchecked LLM text | A single hallucinated number would break the whole promise |
| Recommendations | Rules over evidence, with a backtest | LLM brainstorming | Every recommendation is traceable and its confidence is earned, not asserted |
| Out-of-format questions | Refuse with the nearest supported question | Free-form SQL fallback | Not enough time to make free SQL safe and verified; refusal keeps the zero-error promise |

## What the build taught me

- **Two engines cannot catch a wrong column.** With the Status column removed, role detection picked `Courier Status` as the order status. Both engines agreed on a 4.4% cancellation rate, so it was marked Verified. The independent robustness check (`eval/robustness.py`) caught it, not the engines. The fix: header words like "courier" now rule a column out of the status role. A second eval failure exposed city names that differed only in case ("NEW DELHI", "New Delhi"); city spellings are now merged during cleaning.
- **512 MB is small.** The first deploy ran out of memory on Render's 512 MB instance while loading and cleaning the 1.29 lakh-row sample at startup. Scanning and cleaning the sample moved to `docker build` (`python -m app.prepare_sample`), so the running app only reads prepared files. Peak memory is now 265 to 277 MB in a 512 MB container (`scripts/memcheck.py`).
- **Providers change under you.** The model the PRD was written around, Llama 3.3 70B on Groq, was retired by Groq on 16 Aug 2026. The planner moved to `openai/gpt-oss-120b` on Groq, and NVIDIA NIM was added as a fallback for rate limits, server errors and timeouts. NIM does not serve `openai/gpt-oss-120b`, so the fallback uses Nemotron 3 Super, chosen after a comparison on the golden anchors.
- **Free tiers have daily limits.** Groq's free tier allows 200,000 tokens a day for this model, and one full eval used about 145,000 before the prompt was trimmed (about 125,000 now). Repeated runs hit the cap in the middle of the eval. Plans are now cached on disk, keyed by prompt version, dataset schema and question, so unchanged questions are not re-asked. A small seed of checked plans for the example and eval questions is loaded into the image at build time.

## Limitations and next steps

- **What Verified means.** Verified means two independent engines ran the same plan and got the same result. It catches calculation and cleaning bugs. It does not catch a question that was read wrongly: a misread plan gives the same wrong answer in both engines. That is why the plan is always shown and editable, and why the eval counts "verified but misread" separately.
- **No causal claims.** Recommendations describe associations in past data. The fulfilment rule checks that the gap holds inside each of the top four categories, which removes the most obvious confounder, but other causes such as courier, region or SKU mix remain, and the card says so.
- **Three months of data.** The sample covers 31 Mar to 29 Jun 2022, and March has one day. There is no forecasting, and each backtest uses a single held-out month.
- **Place names that are both a city and a state.** "New Delhi" and "Pondicherry" can be read as a city or as a state, and the model picks one silently (eval questions x07, and x06 on NIM). The planner should ask instead.
- **Slow fallback.** When Groq is unavailable, NIM answers, but planner calls take a median of about 3 to 4 seconds with spikes past 25 seconds. If the sentence takes more than 20 seconds, the template sentence is shown.
- **Single-process state.** Rate limits (30 questions per 10 minutes and 5 uploads per hour per client) and provider cool-downs are kept in memory, so a restart resets them, and more than one worker would count separately. The client address comes from the first `X-Forwarded-For` entry behind the proxy, which a determined client can fake.
- **No accounts.** Anyone with a dataset id can read that dataset until it expires. Datasets and evidence cards are deleted after 24 hours. Storage is the container's local disk, so a redeploy removes everything except the bundled sample.
- **Other known gaps** (from `docs/LATER.md`):
  - the cancelled rule is literal (Status exactly "Cancelled");
  - CSV downloads do not neutralise cells that start with `=`;
  - city spellings beyond case and spaces (Bangalore and Bengaluru) are not merged;
  - the second-file demo and a browser end-to-end test are not done;
  - an LLM sentence can use a wrong word ("peak") with correct numbers.

## Privacy and data

- **Your file** is stored only on the server. It is deleted after 24 hours, or immediately with "Delete my data now" in the workspace header, which removes the file, its cleaned copy and the evidence behind every answer. The shared sample cannot be deleted.
- **Saved question plans** (which measure, grouping, filters and dates a question asked for, not rows from your file) are kept for up to 7 days so repeated questions are faster. "Delete my data now" does not remove them.
- **No accounts and no analytics.** The server keeps a technical log of each request (time, path, outcome, duration), never rows, cell values or questions. A dataset is reached by a random id with no login, so anyone who has that id can open it until it is deleted.
- **What the AI provider receives.** Saabit uses Groq, with NVIDIA as a backup, only to read the question and to phrase the answer; every number is computed on the server by code.
  - To plan a question: the question, the kinds of columns the file has (such as state or category), the short lists of allowed values for columns that have few of them (for example state names), and the file's date range.
  - To write the answer sentence: the question and a table of totals Saabit already computed (at most 20 rows).
  - Never raw rows from the file.
- What the providers do with the data they receive is set by their own policies: [Groq](https://groq.com/privacy-policy/) and [NVIDIA](https://www.nvidia.com/en-us/about-nvidia/privacy-policy/).

The same text is on the app's `/privacy` page.

## Run it locally

Windows, PowerShell, Python 3.11, Node 22 or later.

```powershell
git clone https://github.com/AnanyaPatel3551/Saabit.git
cd Saabit

# If scripts are blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
py -3.11 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd frontend; npm ci; cd ..

# API keys: copy the example and fill in GROQ_API_KEY (and NIM_API_KEY for the fallback)
Copy-Item .env.example .env
notepad .env

# Prepare the sample (the Docker image does this at build time)
cd backend; .\.venv\Scripts\python.exe -m app.prepare_sample; cd ..

# Tests: backend (live LLM tests are excluded), eval rubric, frontend
.\tasks.ps1 test
backend\.venv\Scripts\python.exe -m pytest eval\tests -q
cd frontend; npm test; cd ..

# Run the app: two terminals, then open http://localhost:5173
.\tasks.ps1 dev-backend
.\tasks.ps1 dev-frontend

# Check both LLM providers (uses one small call each)
cd backend
Get-Content ..\.env | ForEach-Object { if ($_ -match '^([A-Za-z_]+)=(.+)$') { Set-Item "Env:$($Matches[1])" $Matches[2] } }
.\.venv\Scripts\python.exe -m app.cli llm-check
cd ..

# Eval: about 18 minutes on Groq (about 125,000 of the 200,000 daily free tokens), then robustness checks
.\tasks.ps1 eval --no-cache
.\tasks.ps1 eval --provider nim --no-cache    # the NIM fallback instead
.\tasks.ps1 eval --only s01 x01 u01           # a few questions; saved as eval\results\partial.*

# Score the manual baseline after filling eval\baseline\baseline_results.csv
backend\.venv\Scripts\python.exe eval\baseline\score_baseline.py
```

Live LLM tests run only on request (`.\tasks.ps1 test-live`) because they spend the provider's rate limit.

## Data

The sample is the "E-Commerce Sales Dataset" (`Amazon Sale Report.csv`): 128,975 rows and 120,378 unique orders from 31 Mar to 29 Jun 2022. It is published on Kaggle by The Devastator (https://www.kaggle.com/datasets/thedevastator/unlock-profits-with-e-commerce-sales-data), from an original source by ANil (https://data.world/anilsharma87).

Licence: Kaggle lists it as "Other (specified in description)", and the description asks only that the original authors be credited. No licence text explicitly grants or forbids redistribution (checked 30 Sep 2026); see `data/sample/README.md`.

Credit: Data from the "E-Commerce Sales Dataset" by ANil (data.world/anilsharma87), published on Kaggle by The Devastator.

A second, **synthetic** sample (`data/sample_shopify/shopify_synthetic.csv`) shows a differently shaped export: Shopify-style headers (`Order Number`, `Created at`, `Total`, `Financial Status`, `Shipping Province`) and DD/MM/YYYY dates. Every row is made up by `data/sample_shopify/make_synthetic.py` from a fixed seed; it is not real sales data. The app labels it "Synthetic data", and it goes through the normal confirm screen ("Try a different file format" on the landing page).
