# Stage 5: natural-language assistant

Run on 2026-10-12.

## How a question is answered

1. **Screen.** Empty, over-long (300 characters) or SQL-shaped input is refused before anything else runs. SQL-shaped means a semicolon, a SQL comment, a statement keyword followed by `from` / `into` / `table` / `set`, or a system catalogue name.
2. **Find names.** Product and business partner names in the question are looked up in ADempiere. Exact phrases are matched first; a close spelling ("Joe Blok") is accepted and the answer says how it was read.
3. **Match.** `sentence-transformers/all-MiniLM-L6-v2` turns the question into a vector, which is compared with the vectors of the example phrasings of each approved intent. The intent of the nearest example wins if the cosine similarity is at least 0.55.
4. **Validate parameters.** Period, top-N and names are extracted by fixed rules, not by the model. An intent that needs a product or customer is not answered unless that name was found in ADempiere.
5. **Run.** The intent's handler runs fixed SQL over the `insightai` views with bound parameters, restricted to the session's client and organisations, through the read-only role.
6. **Explain.** The answer sentence is filled in from the rows returned, by a template. It states the period used, and says so when no period was given and the default was applied.

MiniLM is an embedding model. It never produces text or SQL here, and no generative model is used. Nothing leaves the machine: after the first download the model loads from `models/`.

## Why it is separate from the existing "Ask AI"

Ask AI sends ERP rows to an external LLM that writes its own SQL, runs it as the database superuser and has no organisation filtering. InsightAI's assistant can only run the queries listed below, as a role that can read nothing but the `insightai` views, within the user's organisations. The two do different jobs and Ask AI is left untouched.

## What it can answer

| Intent | Example | Parameters |
|---|---|---|
| Total sales | "What were our total sales last month?" | period |
| Total purchases | "How much did we spend on purchases last month?" | period |
| Top products by sales | "What were our top five products by sales last month?" | period, top-N |
| Top customers by sales | "Who are our top customers?" | period, top-N |
| Sales by product category | "What are sales by product category?" | period |
| Top suppliers by purchases | "Who are our biggest suppliers?" | period, top-N |
| Sales to one customer | "How much did we sell to Joe Block this year?" | customer (required), period |
| Sales of one product | "How many Oak Tree were sold this year?" | product (required), period |
| Declining sales, still in stock | "Which products have declining sales and high current inventory?" | period |
| Overdue customer invoices | "How much money is tied up in overdue invoices?" | customer (optional) |
| Open customer invoices | "Which customers owe us the most?" | customer (optional) |
| Stock of one product | "How many Oak Tree do we have in stock?" | product (required) |
| Inventory value | "What is our inventory worth?" | |
| Slow-moving stock | "Which products are slow moving?" | |
| Stockout risk | "Which products are likely to run out of stock in the next 30 days?" | uses the real-data forecast; horizon fixed at 4 weeks |
| Supplier delivery delays | "Which suppliers have the longest delivery delays?" | period |

Two further classes exist only to decline well: requests to change data ("create a purchase order") get a read-only explanation, and a set of out-of-scope topics (staff, budgets, competitors, general knowledge, how-to) catches look-alike questions.

Periods understood: this/last week, month, quarter and year; year to date; "last N days/weeks/months/years"; "in 2025"; "in September [2026]"; "since June"; "all time". With no period, the last 12 months are used and the answer says so.

## How well the matching works

Measured with `scripts/calibrate_assistant.py` on two sets of questions in `tests/assistant_questions.py`, none of them worded like the examples when written.

| Matcher | Question set | Right | Wrong answer | Declined | Unsupported questions declined |
|---|---|---|---|---|---|
| MiniLM, threshold 0.55 | Development (33 supported, 15 unsupported) | 32 | 0 | 1 | 15 of 15 |
| MiniLM, threshold 0.55 | **Held-back test (28 supported, 12 unsupported)** | **24** | **1** | **3** | **12 of 12** |
| Keyword fallback | Development | 26 | 0 | 7 | 15 of 15 |
| Keyword fallback | Held-back test | 13 | 0 | 15 | 12 of 12 |

- The development set was used to pick the threshold and to add example phrasings and out-of-scope topics, so its figures are optimistic. The held-back set was written afterwards and nothing was changed after seeing its results; it is the figure to rely on: 86% answered correctly, 11% declined, 4% (one question) answered with the wrong intent.
- The one wrong answer: "Which products haven't shipped for a long time?" was read as supplier delivery delays instead of slow-moving stock. Every answer shows "Understood as: ..." so a misreading is visible, but it is not prevented.
- Three supported questions were declined ("How much turnover did we have in the last 3 months?", "Sales figures for 2026 please", "Who is behind on paying us?"). Declining lists the closest supported questions.
- The sets are small and written by the same person who wrote the intents. Treat the percentages as indicative.
- The threshold trades wrong answers against refusals. On the held-back set, 0.45 to 0.50 answers one unsupported question and gets two supported ones wrong; 0.65 gets none wrong but declines 8 of 28.

Before the first tuning round the matcher got 4 of 33 development questions wrong and scored two unsupported questions above the threshold. Three changes fixed that: exact name matches now take precedence over close spellings (the product "Patio Sun Screen" had also been read as the customer "Patio Fun"), intents that need a name the question does not contain are not offered when a different kind of name was found, and the out-of-scope class was added.

## Fallback

Without `sentence-transformers` or the model, matching falls back to keyword sets. It answers fewer questions (13 of 28 on the held-back set) but declined rather than guessed in every tested case, and each answer states that keywords were used and why.

## Checks against hand-written SQL

Four answers are compared in the test suite with SQL written separately for the test: top products for September 2026, the overdue total and invoice count, stock of a product, and sales to a customer for the year. All match. A restricted role's total is checked against its own organisations only.

Answers on GardenWorld today, as GardenWorld Admin:

| Question | Answer |
|---|---|
| Top five products by sales last month | Only 3 had sales: Planting Service 1,752.75, Travel cost 350.00, Patio Sun Screen 247.50 |
| Money tied up in overdue invoices | USD 606.95 in 4 invoices (Joe Block 445.83, C&W Construction 161.12) |
| Suppliers with the longest delivery delays | None late: both rateable receipt lines in the last 12 months were on time |
| Declining sales and high inventory | None found; there are no sales in the earlier period to compare with |
| Likely to run out in the next 30 days | Cannot be answered: no product has enough shipment history to forecast. The synthetic demo is not used |

## Limits

- It answers only the listed intents. A new kind of question needs a new intent in `insightai/assistant/intents.py`.
- One product and one business partner per question. Warehouse, category and organisation names in a question are not read.
- A name the intent does not use is reported as unused rather than applied ("Top products for Joe Block" answers for all customers and says so).
- English only.
- Each question is independent; there is no follow-up context.

## Cost

About 165 ms per question on this machine once loaded. The model is 88 MB on disk and loads in the background when the service starts.
