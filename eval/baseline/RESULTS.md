# Baseline results: Saabit vs a code-executing chatbot (20 questions)

## Who was compared

- **ChatGPT (model not recorded), web app with file upload and code execution, 2026-10-02.**
  Shared conversation: https://chatgpt.com/share/6abf6a05-3b40-83e8-80b4-279ce6130ea9
  Its reply is saved verbatim in `chatgpt_raw_2026-10-02.md`.
- **Saabit, planner on NVIDIA NIM `nvidia/nemotron-3-super-120b-a12b`** (the fallback
  provider), from the full eval run of 2026-10-02 01:07 made with `--no-cache` (no saved plans
  were used). Numbers are computed by Saabit's two engines, not by the model.

## Method

ChatGPT was used in **one conversation**: the CSV (`data/sample/amazon_sale_report.csv`) was
uploaded once and **all 20 questions were sent in one message**, worded exactly as in
`eval/questions.yaml`, with **no hints or corrections**. One conversation can only help
ChatGPT (it can reuse its own earlier work and keep the file loaded), so this comparison is
conservative. The PRD's stricter method is one fresh chat per question.

Its answers were copied into `baseline_template.csv` exactly as stated (₹ and commas removed),
and scored with the same rules as Saabit (`eval/scoring.py`, unchanged) by
`score_baseline.py`. Expected values come from the independent answer key
(`eval/answer_key/questions.py`, plain pandas, never imports the app). Every ChatGPT miss below
was reproduced with plain pandas in `reproduce.py` (also independent of the app).

## Headline

| | Answerable correct | Unanswerable refused | Total |
|---|---|---|---|
| Saabit (NIM, Nemotron 3 Super) | 16 / 17 | 3 / 3 | **19 / 20** |
| ChatGPT (model not recorded) | 2 / 17 | 2 / 3 | **4 / 20** |

No miss was classified as a definition difference (see b03 below), so the headline is the same
with or without that exclusion.

## Question by question

| id | Question | Answer key | Saabit | ChatGPT |
|---|---|---|---|---|
| s01 | Total revenue across all months | ₹7,16,73,394 | ₹7,16,73,394 · right | ₹7,85,92,678.30 · wrong |
| s03 | Average order value overall | ₹694.56 | ₹694.56 · right | ₹652.88 · wrong |
| s05 | Revenue from Amazon fulfilment | ₹5,05,93,039 | ₹5,05,93,039 · right | ₹5,43,22,151 · wrong |
| s07 | Cancellation rate for kurta | 14.64% | 14.64% · right | 14.55% · wrong |
| s08 | Revenue from Karnataka in May | ₹31,07,811 | ₹31,07,811 · right | ₹33,93,125.07 · wrong |
| b01 | Top 5 states by orders | Maharashtra 20,780 … Uttar Pradesh 10,062 | same · right | same · **right** |
| b03 | Orders by fulfilment type | Amazon 84,002; Merchant 36,376 | same · right | Amazon 82,989; Merchant 37,389 · wrong |
| b09 | Top 5 states by revenue | Maharashtra ₹1,22,24,770 … | same · right | Maharashtra ₹1,33,35,534 … · wrong |
| b10 | Category with the most orders | Set, 47,845 orders | same · right | Set, 50,284 rows · wrong |
| t01 | Monthly revenue Apr–Jun 2022 | ₹2,62,34,520 / ₹2,39,53,534 / ₹2,13,90,530 | same · right | ₹2,88,38,708 / ₹2,62,26,477 / ₹2,34,25,809 · wrong |
| t04 | Amazon vs Merchant cancellation, May 2022 | 12.53% / 17.14% | same · right | 12.52% / 17.07% · wrong |
| x01 | rajsthan ka cancellation kitna hai | 14.21% of 2,512 orders | same · right | 13.80% (374 / 2,711 rows) · wrong |
| x02 | Orders placed in March 2022 | 158, with a partial-month warning | 158 with the warning · right | 158, no warning · wrong |
| x04 | RJ se kitne orders aaye | 2,512 | 2,512 · right | 2,506 · wrong |
| x05 | orders from orissa | 2,024 | 2,024 · right | 2,021 · wrong |
| x07 | How many orders from New Delhi? | 6,609 (state Delhi) | 5,948 (city New Delhi) · **wrong** | 76 · wrong |
| x08 | april mein total orders kitne the | 45,858 | 45,858 · right | 45,858 · **right** |
| u01 | Profit margin by category | refuse (no cost column) | refused · right | refused · **right** |
| u02 | Share of cash-on-delivery orders | refuse (no payment column) | refused · right | refused · **right** |
| u03 | forcast next month sales | refuse (no forecasting) | refused · right | gave a forecast · wrong |

## Why ChatGPT missed (each reproduced with plain pandas, `reproduce.py`)

| Reason | Questions | Evidence |
|---|---|---|
| **Revenue included cancelled orders** | s01, s03, s05, s08, b09, t01 | Summing `Amount` over every row, cancelled included, gives exactly its numbers (s01 ₹7,85,92,678.30; s05 ₹5,43,22,151.00; s08 ₹33,93,125.07; b09 and t01 match to the paisa). s03 is that total ÷ all 1,20,378 orders = ₹652.88. The metric definition is revenue over orders that are not cancelled. |
| **Rows counted instead of orders** | s07, t04, x01, b10 | Its stated rule was "cancelled rows / all rows": that gives exactly 14.55% (s07), 12.52% / 17.07% (t04) and 374 / 2,711 = 13.80% (x01). For b10 it reported "Set – 50,284 rows", the row count; Set has 47,845 distinct orders. It stated this rule openly, but the question asks about orders. |
| **State spellings not merged** | x01, x04, x05, x07 | Counting only the exact spelling "Rajasthan" gives 2,506 orders (x04) and 2,711 rows (x01); RJ, Rajsthan and Rajshthan add the rest of the 2,512. Counting only "Odisha" gives 2,021 (x05); "Orissa" adds 3. Counting only the state written "New Delhi" gives exactly 76 (x07); the state Delhi has 6,609 orders. |
| **No partial-month warning** | x02 | ChatGPT gave **no partial-month warning in its x02 answer**. It mentioned March being partial only inside its u03 forecast answer. The value (158) was right; the required warning was missing. |
| **Forecast instead of refusal** | u03 | It produced a July 2022 forecast (≈ ₹2,07,50,766, linear trend on Apr–Jun) instead of saying three months of data cannot support one. |
| **Unexplained miscount** | b03 | See below. |

### b03 in detail

- Plain pandas gives **84,002 Amazon / 36,376 Merchant** distinct orders. These are the answer
  key and Saabit's figures.
- **No order in the file has lines of both fulfilment types** (0 mixed orders). So every
  reasonable way to count orders per type gives the same split:
  - distinct orders within each type;
  - each order counted once by its first line;
  - each order counted once by its last line;
  - after removing duplicate rows.
- ChatGPT's 82,989 / 37,389 adds up to exactly 1,20,378 orders. So it counted each order once,
  but placed 1,013 Amazon-fulfilled orders under Merchant.
- No reading of the file reproduces it. Tried:
  - the `fulfilled-by` column;
  - ship-service-level;
  - non-cancelled lines only;
  - B2B only;
  - sales channel.
- Its row counts (89,698 / 39,277) are right.
- **This is therefore not a definition difference** and is counted as a miss.

## Notes on fairness

- **Saabit's one miss, x07,** is also a reading problem: it took "New Delhi" as the city (5,948
  orders) rather than the state (6,609). It is counted against Saabit.
- **The Saabit run predates the fix** that keeps the partial-month note off all-time totals, so
  its run shows that note on several answers. Extra notes are never penalised for either side,
  and no score depends on them except x02.
- **The ChatGPT model name was not recorded** at the time of the run; the shared link above
  shows the conversation.
