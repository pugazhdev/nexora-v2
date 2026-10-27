# Factory Price Research: Design

Date: 2026-10-26
Branch: `version-2.0` (fresh build; `main` keeps the old medicine app untouched)
Status: draft for approval

## 1. Intent

PharmaSource is being repurposed. It stops comparing retail prices for medicines and becomes a
research tool for **hospital consumables** (syringes, masks, gloves, cannulas, urine bags, caps,
pipettes and similar use-and-throw items).

The user is a **dealer or middleman** in India. A client asks them for a consumable. Before they
negotiate with anyone, they want to know two numbers:

1. **What it costs to make**, per unit, with the reasoning and sources behind it.
2. **The lowest and highest price a manufacturer actually sells it for**, per unit, with a direct
   link to each listing.

Knowing these, the dealer can tell a fair deal from an inflated one. The tool is for research only.
It does not place orders, take payments, or contact suppliers. Every search is a one-off piece of
research; there is no notion of a returning requirement or a client account.

The value of the product is the **research workflow**: turning a photo or a pasted requirement into
a precise specification, finding real manufacturer listings, reading them correctly, and refusing
to show a number it cannot back with a source.

## 2. Goals, non-goals, anti-goals

### Goals

- Input is an image **or** pasted text (or both). Either alone must work.
- Detect every consumable in the input. When there is more than one, the user ticks which to
  research. Selected items are researched **one after another**.
- Ask only the questions needed to pin down the exact variant (capacity, size, type, material,
  sterility, quantity). The questions are generated per product, never hard-coded.
- Nothing is searched until the user confirms.
- For every researched item, show exactly two cards:
  - **Manufacturing cost** in INR per unit: point estimate, likely range, confidence, cost
    breakdown, numbered citations.
  - **Factory purchase price**: lowest and highest manufacturer price per unit, each a link to the
    listing, plus a calculator (units, GST %, freight) and an expandable list of all manufacturers.
- For products that can sensibly be bought as separate parts, show the part names and a
  **Split and research** button that researches each part on demand.
- India only. INR only. Prices in any other currency are dropped, not converted.
- Factory-direct only: manufacturer websites, plus B2B platforms (IndiaMART, TradeIndia,
  ExportersIndia and similar) **when the seller is the manufacturer**. Retail pharmacies and
  traders are excluded.

### Non-goals

- Medicines and drugs. They are detected and declined with a clear message.
- Ordering, RFQs, contacting suppliers, payments.
- Non-Indian suppliers, currency conversion.
- Multi-user accounts, login, roles. This is a single-user local tool.
- Free-form chat with the agent. The flow is fixed steps.
- Live price monitoring or alerts.

### Anti-goals (would make this a failure even if it technically works)

- **A price without a source.** Every number shown on a card links to the page it came from, or is
  explicitly labelled as a calculation from cited inputs.
- **A trader or retailer shown as a manufacturer.** When the tool cannot tell, it says
  "Unconfirmed"; it never guesses "Manufacturer".
- **A box price shown as a unit price.** Price basis (per piece, per box of 100, per carton) is
  resolved or the offer is excluded from the range.
- **Wrong variant.** A 5 mL syringe listing must not be the "lowest price" for a 2 mL request.
- **Verbose output.** Results are numbers, names, links. Explanations are one line or collapsed.
- **AI-slop UI.** The UI follows the approved mockup (section 9), not a generic landing page.

## 3. Constraints (decided by the user)

| Area | Decision |
|---|---|
| Frontend | React (keep Vite + TypeScript) |
| Backend | FastAPI |
| Database | SQLite only |
| ORM | SQLAlchemy (keep Alembic for migrations) |
| LLM | OpenAI only (vision, reasoning, extraction) |
| Web search | Tavily **and** OpenAI's built-in web search tool, used together |
| Orchestration | LangGraph |
| Design | Solid-glass design system (deeplethe/solid-glass), rich chocolate brown, cream background, Inter font, generous white space |
| Generative UI | Our own small version: the agent returns a typed question schema, React renders it from a fixed set of controls. No CopilotKit / AG-UI. |
| Market | India, INR |

Model ids are configuration (`OPENAI_MODEL`, `OPENAI_VISION_MODEL`), never hard-coded.

## 4. Fresh build

Version 2.0 is written **from scratch** on branch `version-2.0`. The old app on `main` (a medicine
retail-price comparer) is not refactored and none of its domain code is reused. There is no drug or
medicine feature anywhere in version 2.0; the only mention of medicines is the input guard in
section 10 ("Medicines are out of scope").

`backend/` and `frontend/` are replaced by fresh projects. Only these files are carried over, copied
together with their tests, because they are security- or plumbing-critical and already proven:

| Carried over | Why |
|---|---|
| `backend/app/connectors/url_safety.py` (SafeFetcher) | SSRF protection, DNS pinning, redirect checks, size cap, robots.txt. Subtle to get right. |
| `backend/app/identification/image_validation.py` | Magic-byte sniffing, size and pixel limits, EXIF strip, resize |
| `Settings.settings_customise_sources` in `config.py` | `backend/.env` must beat machine-wide variables (this machine has `APP_NAME=eScan Antivirus` set globally) |
| `start.ps1`, `stop.ps1` | One-command start/stop; API on port 8015, web on 5173 with `--strictPort` |

Not carried over: Gemini, PostgreSQL and `psycopg`, `docker-compose.yml`, demo mode, FX, every
medicine rule, the old LangGraph graph, old schemas, models, routes, tests, and the whole old
frontend.

## 5. User flow

The approved mockup is `docs/superpowers/specs/mockups/app-v3.html`.

```
Input ──► Select ──► Details ──► Research ──► Results ──► (optional) Split and research
          (only if     (only if
           >1 item)     questions)
```

1. **Input.** Drop an image, paste text, or both. Press **Analyse**.
2. **Select.** If more than one consumable is found, a tick list appears (all ticked by default
   except items flagged out of scope). If exactly one is found, this step is skipped.
3. **Details.** For each selected item, the generated questions. Quantity is always asked
   (prefilled when the input states it). If an item needs no questions it shows "Looks complete".
   A summary line and **Start research** confirm the run. This is the confirmation gate.
4. **Research.** A queue of items on the left, the live step log of the current item on the right.
   The user may leave; the run continues and shows in the sidebar under Today.
5. **Results.** One tab per item. Two cards plus the optional split strip.
6. **Split and research.** Runs the part research for that item and shows the cheapest
   manufacturer per part and the parts total next to the finished-product price.

The sidebar holds: New research, Research (current), History, Manufacturers (every manufacturer
seen across all research), Shortlist (manufacturers the user starred), Settings, and recent
research grouped by Today / This week with a status dot.

## 6. The agent workflow (LangGraph)

### 6.1 Shape: three graphs, human gates between them

The human steps (select, answer, confirm, split) are API calls **between** graph runs, not
interrupts inside one long graph. State that must survive between steps lives in SQLite tables.

Why: the user can leave, edit answers, come back hours later, or restart the server. Separate,
short-lived graph runs keyed by database rows are simpler to reason about and to recover than a
checkpointed graph paused on an interrupt. It also means no extra checkpointer dependency.

| Graph | Trigger | Runs | Output |
|---|---|---|---|
| **Intake** | `POST /api/research` (Analyse) | inline in the request, about 5 to 20 s | items, questions, splittable flag, parts |
| **Research** | `POST /api/research/{id}/start` (Start research) | background task, one item at a time | cost estimate, offers, purchase range |
| **Part research** | `POST /api/items/{id}/split` (Split and research) | background task | cheapest offer per part, parts total |

The part research graph is the research graph's offer branch compiled with `mode="part"`; it is
not a separate implementation.

### 6.2 Intake graph

```
START
  └─► validate_input
        ├─(invalid)──────────────────────────────► END (error)
        └─► prepare_image (skipped if text only)
              └─► analyse_input        (1 OpenAI call, vision + text, structured output)
                    └─► screen_items   (deterministic)
                          └─► END
```

**validate_input** (deterministic)
- At least one of image or text. Text is trimmed, max 5,000 characters.
- Image: reuse `prepare_image` (type sniffing, size and pixel limits, EXIF strip, resize).

**analyse_input** (LLM, structured output, one call)

Returns `IntakeAnalysis`:

```
items: list of
  name                 "Disposable syringe"
  category             one of: consumable, medicine, equipment, not_medical, unclear
  known_attributes     list of {key, label, value, evidence: "visible on pack" | "stated in text" | "inferred"}
  quantity             {value, unit} or null   (only if stated)
  questions            list of Question (see 6.5), only for attributes not already known
  splittable           bool
  parts                list of {name, typical_material, count_per_unit}   (empty unless splittable)
  image_region_hint    short text, e.g. "left, blue cap"   (helps the user match ticks to the photo)
input_quality          ok | blurry | too_dark | no_product | partial
notes                  one short line for the user, or empty
```

Prompt rules (enforced again in `screen_items`):
- Never invent a value it cannot see or read; mark `inferred` only for safe defaults the user can
  change.
- Ask a question for every attribute that changes price for that product type and is unknown.
- Text and image both present: text wins on conflicts, and the conflict becomes a question.

**screen_items** (deterministic, no LLM)
- Drop `not_medical`; keep `medicine` and `equipment` but mark them out of scope with a one-line
  reason (unticked, disabled in Select).
- Merge duplicates (same normalised name and same known attributes).
- Cap at 10 items; report "showing the first 10" if more.
- Validate every question against the Question schema; drop invalid ones; ensure a `quantity`
  question exists (number, unit `units`), prefilled from `quantity` when present.
- Normalise Indian quantity formats in prefilled values: `1,00,000`, `1 lakh`, `10 boxes of 100`
  (the last becomes a question about unit basis if the box size is unclear).
- If zero in-scope items: return a message chosen by `input_quality` ("The photo is too blurry to
  read. Retake it or paste the requirement as text." etc.).

### 6.3 Research graph (one run per item)

```
START
  └─► build_spec                 (deterministic: answers + known attributes ─► ResearchSpec)
        └─► plan_research        (LLM: queries, synonyms, HSN, bill of materials)
              ├─────────────────────────────────────────────┐
              ▼  OFFER BRANCH                               ▼  COST BRANCH
        discover  (fan-out via Send)                  price_materials (fan-out via Send)
         ├─ tavily_search  x N queries                  one search per material / process input
         └─ openai_web_search x M prompts                └─► compute_cost (deterministic)
              └─► merge_candidates (deterministic)
                    └─► fetch_pages (fan-out via Send, bounded)
                          └─► extract_offers (fan-out via Send, LLM per page)
                                └─► verify_quotes (deterministic)
                                      └─► classify_sellers (deterministic + LLM evidence)
                                            └─► normalise_prices (deterministic)
                                                  └─► match_spec (deterministic + LLM verdicts)
              │                                           │
              └────────────────► join ◄───────────────────┘
                                   └─► check_sanity (deterministic, cross-branch)
                                         ├─(no usable offers and retries left)─► broaden_queries ─► discover
                                         └─► finalise ─► END
```

The two branches run in parallel. `join` waits for both (LangGraph fan-in on a node with two
incoming edges).

#### Node contracts

**build_spec** (deterministic)
Builds `ResearchSpec`: `name`, `attributes` (key/value, answered or known), `quantity`, a canonical
one-line `title` ("Disposable syringe, 2 mL, with needle, 24G, luer slip, sterile"), and
`must_match` (attribute keys that change price: capacity, size, ply, material, gauge). `must_match`
comes from the question metadata (`price_relevant: true`).

**plan_research** (LLM, structured)
Returns:
- `queries`: 4 to 8 Tavily queries mixing: exact title + "manufacturer"; synonyms and trade names
  ("hypodermic syringe", "disposable syringe 2ml"); platform-scoped queries for IndiaMART,
  TradeIndia, ExportersIndia; "manufacturer price per piece".
- `web_prompts`: 1 or 2 prompts for OpenAI web search, asking for Indian manufacturers that publish
  a price for this exact spec.
- `hsn_code` guess (used only to look up GST, always shown as editable).
- `bill_of_materials`: components with material, estimated mass in grams per unit, and process
  steps (moulding, assembly, sterilisation, packing) with the basis for each estimate.

**discover** (fan-out)
- Tavily `/search`: `country: india`, `search_depth: advanced`, `max_results` from settings;
  platform queries use `include_domains`.
- OpenAI Responses API with the built-in `web_search` tool, `user_location` set to India, asking
  for listings as structured output with URLs. Only the URLs and titles are kept as candidates; any
  price it states is ignored until a page fetch confirms it (search-model text is not evidence).
- Each source call has its own timeout and retry policy (`RetryPolicy` on the node). One source
  failing does not fail the run; it is logged in the step feed ("OpenAI web search unavailable,
  continuing with Tavily").

**merge_candidates** (deterministic)
- Canonicalise URLs (existing `canonical_url`), dedupe.
- Drop denylisted domains: retail pharmacies and marketplaces (1mg, PharmEasy, Netmeds, Apollo
  Pharmacy, MedPlus, Amazon, Flipkart, Meesho, JioMart, Smart Medical Buyer, and similar; list in
  config so it can grow).
- Drop non-HTTP(S), non-public, and obviously non-product URLs (search result pages, category index
  pages without a price, PDFs over the size cap).
- Cap candidates per run (default 30) keeping platform diversity (not 30 IndiaMART pages).

**fetch_pages** (fan-out, concurrency limit from settings)
- First try `SafeFetcher` (SSRF safe, robots aware).
- If blocked (403, robots disallow, bot wall, empty JS shell) fall back to Tavily `/extract` for
  that URL. If both fail, the candidate is dropped with a logged reason.
- Page text is cached in SQLite by canonical URL for 24 hours, so repeated research is cheap.
- Page content is **untrusted data**: it is passed to the LLM only inside a clearly delimited data
  block, with instructions that it may contain instructions to ignore.

**extract_offers** (LLM per page, structured)
Returns zero or more `ExtractedOffer` per page:
```
seller_name, seller_city, seller_state
seller_type_claim     manufacturer | trader | distributor | retailer | exporter | unknown
seller_type_quote     verbatim text from the page that supports the claim, or null
product_title
attributes            key/value as written on the page (capacity, size, ply...)
price_quote           verbatim price text, e.g. "₹ 2.10 / Piece"
price_value           number
currency              INR | other
price_basis_quote     verbatim, e.g. "Pack of 100", "Per Box", "Per Piece"
tiers                 list of {min_qty, price_value, quote}
moq_quote, moq_value, moq_unit
gst_quote             verbatim if the page says inclusive/exclusive of GST
price_on_request      bool ("Get Latest Price", "Ask for price")
```

**verify_quotes** (deterministic, the anti-hallucination step)
- Every `*_quote` must appear in the fetched page text after whitespace and currency-symbol
  normalisation. A number whose quote is not found is set to null. An offer whose price quote is
  not found is dropped.
- `price_value` must be parseable from `price_quote` (handles `₹`, `Rs`, `INR`, `1,00,000`
  grouping, `2.5`, ranges like `₹1.80 - 2.20`). Ranges keep the low end as the price and the high
  end as a note.

**classify_sellers** (deterministic rules over verified evidence)
- `Manufacturer` when any of: platform badge or business type says Manufacturer; company site
  describes its own manufacturing plant; ISO 13485 / CDSCO manufacturing licence quoted.
- `Excluded` when the evidence says trader, distributor, retailer, wholesaler, or reseller only.
- `Unconfirmed` otherwise (no evidence either way). Shown with an amber tag.
- **Range rule (user decision):** the lowest/highest range uses confirmed manufacturers only. If
  no offer is confirmed, the range is computed from unconfirmed sellers and the card is labelled
  "Unconfirmed sellers only". All sellers always appear in the expandable list with their tags.
- "Manufacturer and exporter" counts as manufacturer; "trader and manufacturer" counts as
  unconfirmed (platforms let sellers tick both).
- Same company seen on several platforms: merged by normalised name plus city; the cheapest
  verified listing represents it, the others are kept as extra links.

**normalise_prices** (deterministic)
- Currency not INR: drop.
- Per-unit price = price / pack size when the basis is a pack ("Pack of 100" ─► /100). Unknown pack
  size for a pack price: excluded from the range, kept in the list as "price basis unclear".
- Per-kg or per-metre prices for count-based products: excluded from the range unless the spec has
  a unit mass/length that makes conversion exact.
- GST: stored ex-GST. A price marked inclusive of GST is converted only when the same listing
  states the rate. Inclusive with no stated rate: excluded from the range, listed with
  "incl. GST, rate not stated". The HSN guess is never used to convert a price. (Builder call.)
- `price_on_request`: kept in the manufacturer list with a "Price on request" label, never in the
  range.
- Listing older than `OFFER_MAX_AGE_DAYS` (default 180) when the page shows a date: flagged
  "older listing", still shown, excluded from the range.

**match_spec** (deterministic first, LLM only for verdicts on free text)
- For each `must_match` attribute: exact match after normalisation (2 ml = 2 mL = 2cc; 3 ply =
  3-ply) ─► `match`; different value ─► `mismatch` (excluded); not stated ─► `unstated`.
- An offer whose title lists several variants with one price ("1 ml, 2 ml, 5 ml syringes ₹2") is
  `ambiguous` and excluded from the range.
- Only `match` offers form the range. `unstated` offers are listed with "spec not confirmed".
- The LLM is used only to judge free-text attributes that rules cannot normalise, and must return
  the quote it relied on (re-verified).

**price_materials** (cost branch, fan-out)
- One Tavily search per material or process input (e.g. "polypropylene homopolymer price per kg
  India", "SS 304 wire price per kg", "EtO sterilisation job work rate per carton").
- Fetch and extract a price with quote, verified the same way as offers.
- If no cited price is found for an input, the LLM's estimate is used **and labelled
  "estimate, no source"**, which lowers confidence.

**compute_cost** (deterministic)
- Material cost = mass (g) x price (INR/kg) / 1000 for each component.
- Process costs from cited rates, or labelled estimates.
- Overhead and scrap as a configured percentage (default 10%), shown as its own line.
- Range: low/high from the min/max of cited input prices plus or minus mass uncertainty (default
  plus or minus 15%).
- Confidence: High when every material line is cited; Medium when materials are cited but process
  lines are estimates; Low when any material line is an estimate.

**join + check_sanity** (deterministic, cross-branch)
- No usable offers and `retries_left > 0`: go to `broaden_queries` (drop the least important
  `must_match` attribute from the queries only, never from matching; add synonyms), then
  `discover` again. Default one retry.
- Lowest offer below 0.6 x the cost estimate's low bound: flag "unusually low, check the unit
  basis" on that offer.
- Highest offer above 3 x the median of the range: treat as an outlier, exclude from the range,
  keep in the list.
- Single usable offer: lowest and highest are the same listing; the card says "1 manufacturer
  found" and shows one price.

**finalise**
- Lowest and highest are computed **at the requested quantity** using each offer's tiers: the
  applicable tier is the highest `min_qty` that is less than or equal to the quantity. Offers whose
  MOQ is above the quantity are listed with "Min N" and excluded from the range. If that excludes
  **every** offer, the range falls back to each offer's lowest-MOQ tier and the card says "All
  manufacturers need a larger order". (Builder call.) The frontend repeats the same computation live as the user edits Units (shared logic,
  tested on both sides with the same fixtures).
- GST rate prefill: from a cited source for the HSN code if one was found; else empty. Always
  editable.
- Persist the result, the step log, the sources, and update the Manufacturers directory.

#### Part research (on demand)

`POST /api/items/{id}/split` runs, for each part in parallel (fan-out via Send), the offer branch
above with `mode="part"`: the spec is the part name plus material plus the parent item's
dimensions; `must_match` is the part's key dimensions; manufacturer classification and all
verification rules are identical. Part quantity for tiers and MOQ is the parent quantity x
`count_per_unit`; the parts total multiplies each part's unit price by `count_per_unit`. Output per part: cheapest usable offer (or "no manufacturer
found"). The summary shows parts total vs the lowest finished-product price, and states that
assembly and sterilisation are not included.

### 6.4 State, budgets, progress

**Graph state** is a `TypedDict` with list fields using `operator.add` reducers so fan-out
branches append safely (`candidates`, `pages`, `offers`, `material_prices`, `events`).

**Budgets per item** (settings, enforced in nodes; exceeding one stops that branch cleanly and is
logged):

| Budget | Default |
|---|---|
| Tavily search calls | 12 |
| OpenAI web search calls | 2 |
| Pages fetched | 30 |
| LLM extraction calls | 30 |
| Wall-clock per item | 180 s |

**Progress** is emitted by nodes as short events (`phase`, `message`, counts, elapsed) written to
an `events` table and streamed to the browser over SSE. Messages are factual and short: "Found 23
listings (IndiaMART 12, TradeIndia 6, maker sites 5)", "Kept 9 manufacturers, dropped 11 traders".

**Concurrency**: one item runs at a time per research (as requested). A global semaphore limits
concurrent research runs (default 2).

### 6.5 Question schema (generative UI contract)

```
Question
  key             "capacity"
  label           "Capacity"
  help            "Not visible on the pack"      (optional, one line)
  kind            single | multi | number | text | boolean
  options         list of {value, label}          (single and multi only; 2 to 8 options)
  unit            "mL" | "units" | ...            (number only)
  min, max        (number only)
  default         value or null
  required        bool
  price_relevant  bool                            (feeds must_match)
```

The frontend has exactly five controls, one per `kind`. Unknown kinds are dropped server-side.
Answers are validated server-side against the schema before research can start.

## 7. Data model (SQLite)

| Table | Purpose |
|---|---|
| `research` | one Analyse action: input text, image path (stored on disk under `data/uploads/`), title, status, created_at |
| `research_item` | one detected item: analysis JSON, questions JSON, current answers JSON, selected, position |
| `item_run` | one research run of an item: answers snapshot, spec JSON, status, result JSON, split JSON, started_at, finished_at. Editing answers and starting again adds a new `item_run`; results always show the latest run, History can open older runs. (Builder call.) |
| `run_event` | step log rows: run_id, at, phase, level, message |
| `page_cache` | canonical_url, fetched_at, status, text, via (direct / tavily_extract) |
| `manufacturer` | normalised_name, display_name, city, state, website, first_seen, last_seen, starred |
| `listing` | manufacturer_id, item_id, url, platform, unit_price, tiers JSON, moq, observed_at, classification, spec_match |

Item status: `draft ─► ready ─► queued ─► researching ─► done | failed | cancelled | interrupted`.
On server start, any `researching` or `queued` item becomes `interrupted` and the UI offers Retry.

A fresh Alembic initial migration replaces the old one. SQLite runs with WAL mode and a busy
timeout so background writes and API reads do not block each other.

## 8. API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/research` | multipart: image and/or text. Runs intake. Returns research with items and questions. |
| GET | `/api/research` | history list (paged) |
| GET | `/api/research/{id}` | full research with items, answers, results |
| PATCH | `/api/research/{id}/items/{item_id}` | select/unselect, save answers |
| POST | `/api/research/{id}/start` | validates answers, queues selected items, starts research |
| POST | `/api/research/{id}/cancel` | cancels queued and running items |
| POST | `/api/items/{item_id}/retry` | re-runs a failed or interrupted item |
| POST | `/api/items/{item_id}/split` | starts part research |
| GET | `/api/research/{id}/events` | SSE: step events and status changes |
| GET | `/api/manufacturers` | directory, filter by starred |
| PATCH | `/api/manufacturers/{id}` | star / unstar |
| GET | `/api/settings` | which keys are configured, budgets, denylist (read-only in UI v1) |
| GET | `/api/health`, `/api/ready` | as today |

Errors keep the existing uniform shape `{"error": {"code", "message", "details"}}`.

## 9. UI

The approved mockup (`docs/superpowers/specs/mockups/app-v3.html`) is the reference. Open it in a browser; it is clickable. Key rules:

- App shell: glass sidebar on the left, centred content on the right. Form steps (Input, Select,
  Details, Research) use a centred column about 820 px wide; Results uses up to 1180 px, centred.
- Step bar at the top right; completed steps are clickable to go back (editing answers after
  research started creates a new run, it does not mutate a finished result).
- Results per item: **Manufacturing cost** card and **Factory purchase price** card side by side,
  stacked on narrow screens. Split strip below only when `splittable`.
- Calculator: Units (prefilled from quantity), GST % (prefilled when known, always editable),
  Freight in rupees (default 0). Totals at lowest and highest recompute on every keystroke.
  Indian digit grouping (1,00,000).
- Tags: Manufacturer (green), Unconfirmed (amber), Min N (red, row dimmed), Price on request,
  Spec not confirmed, Older listing, Unusually low.
- Font: Inter, tabular numbers. Colour tokens and glass recipe from the mockup (solid-glass rim,
  edge, contact and shade shadows; warm hue). Light theme first; dark theme not in v1.
- Copy is short. No paragraphs on results. Empty and error states say what happened and the next
  action in one line.
- Transitions: 200 to 300 ms fade/rise between steps; spinner only on the active step; no
  skeleton shimmer walls.
- Keyboard and accessibility: every control reachable by keyboard, visible focus ring, labels on
  inputs, colour is never the only signal (tags have text).

## 10. Corner cases

### Input
| Case | Behaviour |
|---|---|
| No image and no text | Analyse disabled; API returns 400 |
| Corrupt, unsupported, or oversized image | Existing image validation errors, shown inline |
| Image and text disagree | Text wins; conflict becomes a question |
| Blurry / dark / no product | No items; message names the problem and suggests text input |
| Photo of a medicine | Item shown, unticked, "Medicines are out of scope" |
| Photo of capital equipment (ventilator) | Shown, unticked, "Equipment, not a consumable" |
| More than 10 items | First 10 shown with a note |
| Same item twice | Merged |
| Text lists items with quantities in Indian formats | Quantities prefilled correctly |
| Quantity in boxes with unknown box size | Unit basis question added |
| Text is not a requirement (gibberish, unrelated) | No items, one-line message |
| Prompt injection inside pasted text or image text | Treated as data; output is schema-only |

### Questions and confirmation
| Case | Behaviour |
|---|---|
| Item needs no questions | "Looks complete", quantity still shown |
| Required answer missing | Start research disabled; field highlighted |
| Number out of range, non-numeric | Inline validation, server re-validates |
| User deselects every item | Start research disabled |
| User edits answers after a finished run | New run on Start; old result kept in history |

### Research
| Case | Behaviour |
|---|---|
| OpenAI key missing or invalid | Analyse blocked with "Set OPENAI_API_KEY in backend/.env" |
| Tavily key missing | Research runs with OpenAI web search only; step log says so |
| Both search sources fail | Item fails with a retry button; partial cost estimate still shown if available |
| Rate limit / quota | Backoff once; then fail with the provider's message |
| Zero candidates | One broadened retry; then "No manufacturer listings found" with the queries used |
| No confirmed manufacturer, some unconfirmed | Range from unconfirmed sellers, card labelled "Unconfirmed sellers only" |
| Only traders / retailers found | Price card empty state "No manufacturer found"; excluded sellers not shown |
| Only price-on-request listings | Range empty; listings shown with links |
| Pack price with unknown pack size | Excluded from range, listed with "price basis unclear" |
| Listing covers several variants at one price | Excluded from range |
| Non-INR price | Dropped |
| Page blocks bots | Tavily extract fallback; else dropped and logged |
| Same manufacturer on several platforms | Merged; cheapest listing shown; others as extra links |
| One very low outlier (likely unit mistake) | Flagged "unusually low" |
| One very high outlier | Excluded from range, kept in list |
| Single usable offer | Lowest = highest; card says "1 manufacturer" |
| Requested quantity below all MOQs | Range uses each offer's lowest-MOQ tier, card says "All manufacturers need a larger order", every row shows "Min N" |
| Material prices not found | Cost lines marked "estimate, no source"; confidence drops |
| Budget exhausted mid-run | Finish with what was found; step log says which budget |
| Wall-clock timeout | Same as budget |
| User cancels | Current node finishes, item marked cancelled, partial results discarded |
| Server restart during research | Item marked interrupted on boot; Retry available |
| User closes the browser | Run continues; visible in sidebar |
| Two research runs at once | Global semaphore queues the second |
| Scraped page tries prompt injection | Data-block isolation plus quote verification: injected numbers cannot pass |

### Split research
| Case | Behaviour |
|---|---|
| Product not splittable | No split strip |
| A part finds no manufacturer | That row says "No manufacturer found"; total marked incomplete |
| Split pressed twice | Second press ignored while running; after done, button becomes "Research again" |

## 11. Testing and evaluation

- **Unit tests** for every deterministic node: quote verification, price parsing (Indian grouping,
  ranges, Rs/INR/₹), pack normalisation, spec matching, seller classification, tier selection at a
  quantity, outlier rules, cost computation, quantity parsing.
- **Graph tests** with fake OpenAI and fake Tavily clients covering every route in section 6
  (no offers ─► broaden ─► still none; one source down; budget exhausted; cancellation).
- **Shared calculator fixtures**: one JSON file of offers plus quantities plus expected
  lowest/highest, run by pytest and Vitest so backend and frontend agree.
- **Recorded page fixtures**: a handful of saved IndiaMART, TradeIndia and manufacturer pages used
  to test extraction and verification offline.
- **Live evaluation set** (manual, run before each phase sign-off): 2 mL syringe with needle,
  3-ply surgical mask, nitrile examination gloves (M, powder-free), IV cannula 20G, urine bag
  2000 mL. For each, record what the tool returned and spot-check every link and number by hand.
  A phase is not done if any shown number fails to match its linked page.

## 12. Phases

Each phase ends with working, tested software and a short demo.

| Phase | Scope | Done when |
|---|---|---|
| **0. Spikes** | Confirm OpenAI web search with structured output works with the configured model; check which of IndiaMART / TradeIndia / ExportersIndia fetch directly vs need Tavily extract; save page fixtures | A short findings note in `docs/`; fixtures committed |
| **1. Foundation** | Fresh backend project; carry over the files in section 4; settings, models, fresh migration; OpenAI and Tavily clients with error mapping | Backend boots on SQLite; carried-over tests and client tests pass |
| **2. Intake** | Intake graph, question schema, `/api/research` create/get/patch, quantity parsing | Image, text, and both produce items and valid questions for the 5 eval products |
| **3. Offer branch** | discover, merge, fetch, extract, verify_quotes, classify, normalise, match_spec, finalise (offers only), events, SSE, start/cancel/retry, restart recovery | Eval products return lowest/highest with links that check out by hand |
| **4. Cost branch** | plan BOM, price_materials, compute_cost, join, check_sanity, broaden retry | Cost card numbers each trace to a cited input or are labelled estimates |
| **5. Split research** | part mode, split API | Syringe and IV set split results check out by hand |
| **6. Frontend shell** | Fresh Vite + React + TypeScript project; design tokens and glass components, sidebar, step bar, Input, Select, Details, Research views wired to the API | Full flow up to the research log works in the browser |
| **7. Results and directory** | Results cards, calculator with shared fixtures, split strip, History, Manufacturers, Shortlist, Settings | Matches the mockup; calculator fixtures pass in both test suites |
| **8. Hardening** | Corner-case table walkthrough, budgets, logging, live eval pass, docs (README, API, workflow) | Every row in section 10 has a test or a recorded manual check |

## 13. Left to the builder

- Exact prompt wording for each LLM node (must follow the rules stated per node).
- Exact denylist contents beyond the named retailers.
- Internal module layout inside `workflow/`, `research/`, `clients/`.
- Whether `price_materials` reuses `extract_offers` or has its own small extractor.
- Component structure in React, as long as the mockup and the five question controls are honoured.
- Default values in section 6.4 and section 6.3 may be tuned after the Phase 0 spikes, with the
  change noted in the findings doc.

## 14. Decisions from the design conversation

Recorded so nothing discussed is lost. "User" means the product owner; everything else in this
document is consistent with these.

**Who and why**
- Users are intermediate dealers / middlemen. They want the lowest possible factory-level cost so
  they are cautious when selecting a deal. Pure research: no previous requirements, no client
  history, no "last time" workflow. (User correction after an off-target question.)
- The product researches **hospital consumables only** (use-and-throw items). No drugs at all.

**Sources and money**
- Direct from manufacturers, not retailers (Tata 1mg, PharmEasy and similar are excluded).
- B2B platforms (IndiaMART, TradeIndia, ...) count when the seller is the manufacturer, with the
  direct link to the listing. (User: "yes count them as well".)
- India only, INR only.
- Cost estimation shown in INR per unit.
- Calculator: units, GST, freight are adjustable by the user. GST is prefilled when the tax is known
  cleanly, and the field is always editable on the card.
- Range rule: confirmed manufacturers only; if none, unconfirmed sellers with a clear label.
  (User: "go with your recommendation".)

**Flow**
- Input is an image or pasted requirement text; either must work.
- Analyse first, then ask for confirmation ("Do you want this searched?") before any deep search.
- Multiple consumables in one image: ask first with an interactive tick list, then research the
  ticked items one by one, finishing one before the next.
- Follow-up questions for unclear inputs (variant, size, capacity, quantity), generated per product,
  never hard-coded (a syringe asks capacity; a mask asks surgical vs N95). User confirmed this must
  be dynamic.
- **Split and research is NOT part of the initial questionnaire.** It is an optional button on the
  results page, shown only for eligible products, with the part names listed before the button
  (e.g. syringe: barrel, plunger, rubber gasket, needle). The earlier "price by parts" toggle on the
  Details step was removed.
- Results page has exactly two cards for every product: (1) manufacturing cost, (2) the lowest and
  highest price they can buy from manufacturers, with cited links. User called the earlier
  four-KPI layout cluttered.

**Robustness (user's two priorities)**
1. The UI must be intuitive and adaptable.
2. The research agent must be robust: break down the input, form search queries, search and scrape,
   then analyse the data. "Every corner case needs to be captured." "Don't do the slop."

**UI and design**
- Agentic app, intuitive buttons and transitions. Design system in the style of
  https://github.com/deeplethe/solid-glass; colour theme rich clean chocolate brown with neat,
  premium, white-spaced, elegant design.
- Mockup v1 was rejected: "looks like an over-modern fashion website", fonts not neat, "looks like a
  single HTML page". Fix: plain neat font (Inter), app shell with a sidebar for History and other
  sections so everything is reachable in a few clicks, good UX principles.
- Mockup v2 feedback: too much empty space on the right; content must be centred.
- Mockup v3 approved ("perfect go with this").
- Generative UI: our own simple version (agent returns typed questions, React renders from fixed
  controls). CopilotKit / AG-UI considered and declined: "simple and robust is enough for now".
- Results must not be verbose.

**Engineering**
- Stack fixed by the user: React, FastAPI, SQLite only, SQLAlchemy, OpenAI, Tavily plus OpenAI
  native web search.
- Build from scratch on branch `version-2.0`; do not refactor the old app.
- Writing style for docs and copy: avoid em dashes.
- Local run: `start.ps1` / `stop.ps1`; API on port 8015 because port 8000 is used by another local
  project; Vite on 5173 with `--strictPort`.
- `backend/.env` must override OS environment variables.
- The OpenAI and Tavily keys in `backend/.env` were pasted into a chat and should be rotated.

**Open**
- App name: "PharmaSource" implies pharmacy/drugs. It is `APP_NAME` in `backend/.env`; the user has
  not chosen a new name yet.
