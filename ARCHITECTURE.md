# Architecture

A FastAPI backend runs three LangGraph graphs. The user's steps (tick items, answer questions,
press Start, press Split) happen **between** graph runs and are saved in SQLite, so nothing is lost
if the browser closes or the server restarts.

```
 Browser (React)                          Backend (FastAPI)                       Outside
 ───────────────                          ─────────────────                       ───────
 Input  ── POST /research ──────────────▶ [1] Intake graph ──────────────────────▶ OpenAI
 Select ┐                                       │ items + questions
 Details┴─ PATCH answers ───────────────▶ SQLite ◀──────────────────────────────┐
 Start  ── POST /start ─────────────────▶ Run queue (one item at a time)        │
 Research ◀── SSE step log ─────────────  └▶ [2] Research graph ────────────────┼▶ Tavily, OpenAI,
 Results ◀── GET /research/:id ─────────       │ ItemResult                     │   supplier pages
 Split  ── POST /items/:id/split ───────▶ [3] Part research (graph [2], part mode)┘
```

## 1. Intake graph: photo or text to items and questions

```
START ─▶ validate_input ─┬─▶ prepare_image ─┐
                         └──────────────────┴─▶ analyse_input ─▶ screen ─▶ END
```

| Node | What it does |
|---|---|
| validate_input | Needs a photo or text; text under 5,000 chars |
| prepare_image | Checks file type and size, strips EXIF, resizes |
| analyse_input | One AI call: finds the consumables and writes the questions each one needs |
| screen | No AI. Drops non-medical items, marks medicines/equipment out of scope, merges duplicates, always adds Quantity, drops malformed questions |

## 2. Research graph: one item to prices and cost

```
START ─▶ plan_research
              │  (fan-out)
              ├─▶ tavily_search ─┐
              └─▶ web_search ────┴─▶ merge_candidates
                                          │  (fan-out, one per page)
                                          ├─▶ fetch_extract ─┐
                                          └──────────────────┴─▶ build_offers
                                                                     │
                        none in range and retries left ◀─────────────┤
                        broaden_queries ─▶ back to search            │
                                                                     ▼
                                                                offers_done
                                                                     │  item mode only
                                                                     ▼
                                                             refine_cost_plan
                                                                     │  (fan-out, one per material)
                                                                     ├─▶ price_material ─┐
                                                                     └───────────────────┴─▶ compute_cost
                                                                                               │
                                                                                         check_sanity
                                                                                               │
                                                                                    finalise ─▶ END
```

| Node | What it does |
|---|---|
| plan_research | AI writes search queries, the product-type words, and a bill of materials |
| tavily_search / web_search | Search B2B platforms and maker sites; web-search links come only from citations |
| merge_candidates | Clean URLs, drop duplicates and retail sites, cap at 30 pages |
| fetch_extract | Fetch the page (Tavily as fallback), AI pulls out every offer with **verbatim quotes** |
| build_offers | No AI. Keeps an offer only if its quotes are on the page; converts box prices to per piece; INR only; sorts manufacturer / unconfirmed / trader; checks the product type and variant |
| broaden_queries | One retry with wider queries when nothing is in range |
| refine_cost_plan | AI re-estimates each cost line for bulk production, kept below the lowest market price |
| price_material | Finds a cited ₹/kg price for each material, verified on the page |
| compute_cost | No AI. Mass × ₹/kg, process estimates, 10% overhead, range, confidence |
| check_sanity | No AI. Flags or removes box prices and outliers; lowers confidence if cost exceeds market |
| finalise | Sorts offers, saves manufacturers, prefills GST, writes notes |

**Part mode** (Split and research) runs the same graph per part, stopping at `offers_done ─▶ finalise`.

## Rules that keep numbers honest

- **No quote, no number.** Price, seller name, quantity break, MOQ and specs must appear on the page,
  next to that listing's own price.
- **Unsure means Unconfirmed.** "Manufacturer" only from a business-type label, own-plant wording, or an
  ISO 13485 / CDSCO licence.
- **Range** uses confirmed manufacturers; falls back to unconfirmed sellers with a label; never traders.
- **Budgets per item** (searches, pages, AI calls, 180 s) stop a branch cleanly with a note.
- **Provider failure** (search down, OpenAI quota) with nothing found fails the item with Retry.

## Code map

```
backend/app/
  intake/      graph.py, screen.py, quantity.py, schemas.py, prompts.py
  research/    graph.py, nodes.py, prompts.py
               quotes.py prices.py spec.py sellers.py tiers.py cost.py sanity.py  (deterministic rules)
  runs/        service.py  (queue, cancel, retry, split, restart recovery)
  clients/     llm.py (OpenAI), tavily.py
  fetch/       pages.py, url_safety.py (SSRF-safe fetch, robots.txt, cache)
  api/         routes.py   repo.py  models.py (SQLite)
frontend/src/
  features/    research (steps), results (cards, calculator), history, manufacturers, settings
  lib/         calculator.ts (same rules and test cases as tiers.py)
shared/        calculator_cases.json, total_cases.json (run by both test suites)
```

More detail: [docs/WORKFLOW.md](docs/WORKFLOW.md) and [docs/API.md](docs/API.md).
