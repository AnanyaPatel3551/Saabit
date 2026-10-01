# Baseline: a code-executing chatbot on the same questions

The PRD's success metrics include "Saabit beats a code-executing chatbot on correctness and
refusals". This folder holds the manual baseline and its scorer.

## Method (PRD "Evaluation plan", Baseline)

1. Use ChatGPT or Claude **with code execution on** and the file
   `data/sample/amazon_sale_report.csv` **uploaded as a file**.
   Do not paste the CSV into the chat: 1.29 lakh rows do not fit, and judges would read it as an
   unfair comparison.
2. **One fresh chat per question.** Upload the file again each time, so no answer leans on an
   earlier one.
3. Type the question exactly as written in `baseline_template.csv`, with no extra hints about
   cleaning, the cancellation rule or state spellings. The trap questions only test something if
   the chatbot gets the same words a seller would type.
4. Record what the chatbot answered (below), then score it with the **same rubric** as Saabit:
   `python eval/baseline/score_baseline.py`.
5. Publish both scorecards, failures included.

Note which product and model you used (for example "ChatGPT, GPT-5, 1 Oct 2026") in the first
row's `notes`.

## Filling the CSV

Copy `baseline_template.csv` to `baseline_results.csv` and fill only the rows you ran. Empty rows
count as "not run" and are left out of both columns.

| Column | What to write |
| --- | --- |
| `answer_given` | The number the chatbot gave, as typed: `₹2,39,53,534`, `14.2%`, `2.40 Cr` and `35141` all work. For grouped questions, use `key=value; key=value` in the order given, e.g. `Maharashtra=20780; Karnataka=16182`. |
| `refused` | `yes` if the chatbot declined or said it could not answer; otherwise leave it blank. |
| `notes` | For a refusal, the chatbot's reason (it is checked for the same words as Saabit's). For a partial-month question, copy any warning it gave (the caveat check looks here). Anything else worth remembering. |

## Rubric (the same as eval.py)

- **Answerable:** the value is within the question's tolerance (counts exact, rupees ±0.01,
  rates ±0.01 points). Grouped answers need the same groups; top-N answers need the same order.
  A required caveat (e.g. "partial" for March) must appear.
- **Unanswerable:** `refused = yes`, and the reason contains one of the question's `reason_any`
  words from `eval/questions.yaml`.

A chatbot that gives a rounded value such as "₹2.40 Cr" for ₹2,39,53,534 is marked wrong, as
Saabit would be. That is deliberate: the product's claim is exact numbers.
