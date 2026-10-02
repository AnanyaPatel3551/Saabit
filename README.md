# Saabit (साबित, "proven")

**Ask your sales data in plain English or Hinglish. Get numbers you can prove.**

🔗 **Live app:** https://saabit.onrender.com
🎥 **Demo video (3 min):** [add video link]
📊 **Presentation:** [add deck link]

[![CI](https://github.com/AnanyaPatel3551/Saabit/actions/workflows/ci.yml/badge.svg)](https://github.com/AnanyaPatel3551/Saabit/actions/workflows/ci.yml)

> PS-04: AI Decision Engine for Business Data · Ananya Patel (solo) · BITS Pillani (Scaler School of Technology)

![Saabit workspace](docs/screenshots/workspace.png)

---

## 💡 Project overview

**The problem.** Indian online sellers have sales files but no analyst. AI chatbots answer their questions confidently and are often wrong. On the same Amazon sales file, ChatGPT gave total revenue as **₹7.86 Cr** because it counted cancelled orders. The real answer is **₹7.17 Cr**.

**The solution.** Saabit is a web app. You upload a CSV or Excel file of orders and ask questions like *"Top 5 states by revenue"* or *"rajasthan ka cancellation kitna hai"*.

**How it works: the AI never writes a number.**

1. **Upload:** Saabit detects the columns, you confirm them, and it cleans the data (cancelled orders, state and city spellings, partial months).
2. **Plan:** the AI turns your question into a small plan (what to count, how to split, which filters). It never produces numbers.
3. **Compute twice:** code runs that plan in two separate ways, with SQL in DuckDB and with pandas.
4. **Check:** the number is shown only when both agree, marked **"✓ Checked twice"**.
5. **Evidence:** every answer shows what was counted, the rows behind it (downloadable as CSV) and the technical details.
6. **Honest refusals:** if the file can't answer (profit with no cost column, or forecasts from 3 months of data), Saabit says so and suggests a question it can answer.

**Key features**

- English and Hinglish questions.
- Checked twice, with evidence for every answer.
- Automatic insights.
- Cleans messy data.
- Partial months flagged.
- The same question gives the same answer.
- A backup AI, plus template sentences if the AI is down.
- A private key for each upload, and files deleted after 24 hours.

**Results** (full details in [docs/DETAILS.md](docs/DETAILS.md))

| Test | Result |
| --- | --- |
| 50 eval questions, answer key built separately in plain pandas | **39/40** answerable right, **10/10** refused correctly |
| Wrong numbers marked "Checked twice" | **0** |
| 15 golden anchor questions | **15/15** |
| Answer time (median / 95th percentile) | **1.27 s / 2.73 s** |
| Same 20 questions vs ChatGPT | **Saabit 19/20 · ChatGPT 4/20** |
| Automated tests | **409 passed** |

---

## 🛠️ Technologies used

| Layer | Tools |
| --- | --- |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, Recharts |
| Backend | Python 3.11, FastAPI, Pydantic |
| Calculation (two engines) | DuckDB (SQL built with sqlglot) and pandas, with PyArrow / Parquet |
| AI (plans and sentences only) | Groq `openai/gpt-oss-120b` (main), NVIDIA NIM `nemotron-3-super-120b-a12b` (backup) |
| Testing | pytest, Vitest, custom eval harness (`eval/`) |
| Deployment | Docker (multi-stage), Render, GitHub Actions CI |

---

## ⚙️ Setup & installation steps

### You need

- **An API key from Groq.** Get one for free at [console.groq.com](https://console.groq.com/keys). An NVIDIA NIM key is optional; it's only used as the backup AI.
- **Docker**, for the easiest setup on any operating system. If you don't use Docker, you need **Python 3.11** and **Node.js 22 or later**.

### 1. Get the code

```bash
git clone https://github.com/AnanyaPatel3551/Saabit.git
cd Saabit
```

### 2. Add your API key

Copy the example file:

```bash
cp .env.example .env              # Windows PowerShell: Copy-Item .env.example .env
```

Open `.env` and fill in this line (everything else can stay empty):

```
GROQ_API_KEY=your_groq_key_here
```

### 3a. Install with Docker (recommended)

```bash
docker build -t saabit .
```

### 3b. Or install without Docker

**Windows (PowerShell):**

```powershell
py -3.11 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd backend; .\.venv\Scripts\python.exe -m app.prepare_sample; cd ..
cd frontend; npm ci; cd ..
```

**macOS / Linux:**

```bash
python3.11 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
(cd backend && .venv/bin/python -m app.prepare_sample)
(cd frontend && npm ci)
```

---

## 🚀 How to run the project

### With Docker

```bash
docker run --rm -p 8000:8000 --env-file .env saabit
```

Open **http://localhost:8000**.

### Without Docker (two terminals)

**Windows:**

```powershell
.\tasks.ps1 dev-backend      # terminal 1: API on port 8000
.\tasks.ps1 dev-frontend     # terminal 2: app on port 5173
```

If PowerShell blocks scripts, run this once first: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

**macOS / Linux:**

```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000 --env-file ../.env   # terminal 1
cd frontend && npm run dev                                                              # terminal 2
```

Open **http://localhost:5173**.

### Try it

1. Click **Try sample data**. This loads the Amazon India sales file: 1,28,975 rows, Mar–Jun 2022.
2. Tap an example question, such as **Top 5 states by revenue**, then press **Ask**.
3. Look for **✓ Checked twice**, then open **See how we got this** for the evidence.
4. Try Hinglish: `rajasthan ka cancellation kitna hai`.
5. Try something it should refuse: `forecast next month revenue`.

### Run the tests

```powershell
.\tasks.ps1 test                        # backend tests (Windows; no live AI calls)
cd frontend; npm test                   # frontend tests
.\tasks.ps1 eval --no-cache             # full 50-question eval (uses Groq tokens)
```

On macOS / Linux, run the backend tests with: `cd backend && .venv/bin/python -m pytest -m "not live"`

---

## 📁 Repository structure

```
Saabit/
├── backend/          FastAPI app: ingest, cleaning, planner, SQL + pandas engines, checks
│   ├── app/          source code (core/, api/, llm/)
│   └── tests/        409 backend tests
├── frontend/         React + TypeScript app
├── eval/             50 test questions, independent answer key, ChatGPT baseline, results
├── notebooks/        golden answers worked out in plain pandas
├── data/             sample datasets (real Amazon India file + synthetic Shopify-style file)
├── docs/             PRD, detailed write-up, screenshots
├── scripts/          memory and timing checks
├── Dockerfile        one image: builds the frontend, serves everything from FastAPI
├── render.yaml       Render deployment
└── tasks.ps1         Windows task runner (dev, test, lint, eval)
```

---

## 🤖 AI tools disclosure

- **Claude (Anthropic):** planning, the PRD and design reviews.
- **Claude Code:** wrote most of the code from my phase-by-phase specifications. I reviewed, tested and ran every change.
- **Inside the app:** Groq GPT-OSS 120B (main) and NVIDIA Nemotron (backup) only turn questions into a plan and phrase the final sentence. They never produce numbers; code computes every number twice.
- **ChatGPT:** used only as the comparison baseline (`eval/baseline/`).

---

## 📄 Data credit

Sample data: "E-Commerce Sales Dataset" by ANil (data.world/anilsharma87), published on Kaggle by The Devastator. The Shopify-style sample is fully synthetic. See `data/sample/README.md`.

**More detail:** design decisions, the full eval method, privacy, limitations and lessons learned are in [docs/DETAILS.md](docs/DETAILS.md).