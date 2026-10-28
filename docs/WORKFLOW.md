# Workflow

The agent is three short LangGraph graphs. The human steps (tick items, answer questions, Start research,
Split and research) are API calls **between** graph runs, never interrupts inside one graph. Everything
that must survive between steps is a row in SQLite (`research`, `research_item`, `item_run`, `run_event`),
so the user can leave, edit answers, or restart the server.

| Graph | Built in | Trigger | Runs |
|---|---|---|---|
| Intake | `backend/app/intake/graph.py` | `POST /api/research` (Analyse) | Inline in the request |
| Research (item mode) | `backend/app/research/graph.py`, `build_research_graph("item")` | `POST /api/research/{id}/start` | Background task, one item after another |
| Part research (part mode) | same builder, `build_research_graph("part")` | `POST /api/items/{id}/split` | Background task, parts in parallel |

Node bodies live in `backend/app/research/nodes.py`; the deterministic rules they call live in small
modules next to it (named in each section below). Runs are scheduled by `backend/app/runs/service.py`.

## 1. Intake graph

```
START
  -> validate_input
       -> prepare_image   (only when an image was sent)
       -> analyse_input   (1 OpenAI call, vision + text, strict structured output)
            -> screen     (deterministic)
                 -> END
```

| Node | What it does | Code |
|---|---|---|
| validate_input | Needs an image or text; text is trimmed and capped at `MAX_TEXT_CHARS` | `intake/graph.py` |
| prepare_image | Sniffs the real type (JPEG, PNG, WebP), size and pixel limits, strips EXIF, resizes to `IMAGE_MAX_SIDE` | `intake/image.py` |
| analyse_input | One structured call. The input goes inside `<user_input>` and the prompt says it is data, never instructions. Rules in the prompt: never invent a value; ask a question for every unknown price-changing attribute; text wins over the photo and a conflict becomes a question; quantity only when stated; parts only when buying them separately is realistic | `intake/prompts.py` |
| screen | Drops `not_medical`; keeps medicines and equipment unticked with a one-line reason; merges duplicates (same name and known attributes); caps at `MAX_ITEMS` (10) with a note; drops malformed questions; always adds a required Quantity question, prefilled from Indian formats (1,00,000, 1 lakh, 10 boxes of 100); adds "Pieces per box" when boxes have no size; picks the empty-result message from the photo quality | `intake/screen.py`, `intake/quantity.py`, `intake/schemas.py` |

Answers are validated against the question schema on every PATCH and again on Start
(`intake/schemas.py::validate_answers`). Only five question kinds exist: single, multi, number, text,
boolean.

## 2. Research graph (one run per item)

`RunService.start` turns the item and its answers into a `ResearchSpec` (`research/spec.py::build_spec`),
creates an `item_run`, and runs the graph under a global semaphore (`RESEARCH_CONCURRENCY`, default 2)
with a hard timeout of `ITEM_TIMEOUT_SECONDS` plus a grace period.

```
START
  -> plan_research                                   (LLM: queries, web prompts, product type terms, BOM)
       OFFER BRANCH
       route_discover (fan-out)
         -> tavily_search x N   -> merge_candidates
         -> web_search x M      -> merge_candidates
       merge_candidates
         -> route_fetch (fan-out) -> fetch_extract x K
              -> build_offers
                   -> route_after_offers
                        |- nothing in range, retry left -> broaden_queries -> route_discover
                        '- otherwise -> offers_done
       COST BRANCH (item mode only, after the offers so it sees the market prices)
       offers_done -> refine_cost_plan                (LLM: re-estimate per-piece lines against the market range)
         -> route_materials (fan-out, 1 per material) -> price_material x M
              -> compute_cost_node -> check_sanity -> finalise -> END
```

Part mode compiles the same graph without the cost branch: `offers_done -> finalise`.

### Nodes

| Node | What it does | Code |
|---|---|---|
| plan_research | One LLM call: 4 to 8 Tavily queries, 1 or 2 OpenAI web search prompts, HSN guess, the product `type_terms`, and a per-piece bill of materials and process steps with estimates. On failure: "Planning failed, using basic searches", two queries built from the spec title, no BOM (so no cost card). Part mode drops the BOM | `nodes.py::plan_research`, `research/prompts.py` |
| tavily_search | Tavily `/search` (India, advanced depth); platform queries are restricted to that platform's domain | `nodes.py::tavily_search`, `clients/tavily.py` |
| web_search | OpenAI Responses API with the `web_search` tool, user location India. Only URLs and titles are kept; any price it states is ignored | `nodes.py::web_search`, `clients/llm.py` |
| merge_candidates | Canonical URLs, dedupe, drop denylisted retail and marketplace domains (1mg, PharmEasy, Netmeds, Amazon, Flipkart and others, plus `EXTRA_DENYLIST`) and non-product pages, cap at `MAX_CANDIDATES` (30) interleaving platforms | `nodes.py::merge_candidates`, `research/domains.py` |
| fetch_extract | One page per candidate: SQLite cache (24 h), then the SSRF-safe, robots-aware fetcher, then Tavily `/extract` when blocked, thin or a captcha. The page text goes to the LLM inside `<page_data>` with the spec; out comes zero or more offers with verbatim quotes | `nodes.py::fetch_extract`, `fetch/pages.py`, `fetch/url_safety.py` |
| build_offers | Deterministic: verify quotes, attribute values to the right listing, product type gate, spec match, price normalisation, GST, MOQ and tiers, seller classification, duplicate merging (rules below) | `nodes.py::build_offers` |
| broaden_queries | When no offer is in range and `BROADEN_RETRIES` (1) remain: one LLM call for new, broader searches; matching rules are never loosened | `nodes.py::broaden_queries` |
| refine_cost_plan | Item mode, after offers_done: one LLM call (`cost_llm` budget) with the plan's BOM and process lines and the lowest and highest in-range unit price at the requested quantity (or "no market price found"); it re-estimates each line's per-piece mass and estimate so the making cost is consistent with the selling prices. Market prices are context only. On failure the first estimate stays, with a note | `nodes.py::refine_cost_plan` |
| price_material | One Tavily search per distinct BOM material ("X price per kg India"), read the first result (the second only if the first has no price), extract a per-kg price with its quote | `nodes.py::price_material` |
| compute_cost_node | Mass x price per kg per component, process lines from the plan's estimates, overhead and scrap (`OVERHEAD_PCT`, 10%), range from mass uncertainty (`MASS_UNCERTAINTY_PCT`, 15%) and min/max of cited prices | `nodes.py::compute_cost_node`, `research/cost.py` |
| check_sanity | Cross-branch checks of offers against the cost and against each other (rules below) | `nodes.py::check_sanity`, `research/sanity.py` |
| finalise | Sorts offers by price at the requested quantity, picks the GST prefill, adds budget and time notes, saves manufacturers and listings to the directory | `nodes.py::finalise` |

### Verification rules (build_offers)

In order, for every offer the LLM extracted from a page:

1. **Quotes must be on the page.** Every `*_quote` is searched in the fetched text after whitespace and
   currency normalisation. A missing quote is set to null. No price quote (and not price on request) or a
   seller name that is not on the page drops the offer. "Price trend" or "market price" text is not an
   offer price (R39). (`research/quotes.py::quote_in_page`, `nodes.py::_verified`, `::_trend_price`)
2. **Values belong to their own listing.** On a page with several listings, an attribute value or the
   product title counts for an offer only when the nearest listing anchor (its verified price, or its
   seller name for price on request) is this offer's own, within 400 characters, and the value is not
   part of a longer number ("20ml" inside "120ml"). (R26, `nodes.py::_near_listing`)
3. **Right product type.** The verified title must contain one of the plan's `type_terms` as whole words
   (or the last product word of the item name before any "," or "(", skipping units and qualifiers such as
   mL, size, ply, free, sterile: "Urine bag 2000 mL" gives "bag"). A needle listing is never a syringe. (R24,
   `research/spec.py::type_matches`, `::type_terms_of`)
4. **Right variant.** Each `must_match` attribute is compared after normalisation (2 ml = 2 mL = 2cc,
   3 ply = 3-ply = three ply, 20 gauge = 20G, size words). A different value drops the offer. Several
   variants with one price is `ambiguous`, not in range. The primary attribute (capacity, then ply, gauge,
   material, length, size) must be stated for the offer to be in range; an unstated secondary attribute
   keeps it in range with "Spec partly confirmed". `must_match` comes from price-relevant answers, from
   known attributes read from the pack or text, and from a size written in the item name such as "3-ply"
   or "2 mL" (R35). (`research/spec.py::build_spec`, `::match_keys`, `::primary_key_of`)
5. **INR per unit, ex GST.** The price must parse as INR (Rs, INR, rupee sign, Indian grouping, ranges keep
   the low end); any other currency drops the offer. A pack price is divided by its stated count; no count
   gives "Price basis unclear" (not in range). Inclusive GST is removed only when the same listing states
   the rate; otherwise "Incl. GST rate not stated" (not in range). Quantity tiers are kept only when their
   quantity is quoted. (`research/prices.py`, `nodes.py::_unit_price`, `::_tiers`)
6. **Seller type from evidence only.** Manufacturer when a quote near the seller's name says Manufacturer
   (or Manufacturer and Exporter), describes its own plant, or cites ISO 13485 or a CDSCO manufacturing
   licence. Excluded when it says trader, distributor, retailer, wholesaler or similar only. Both, or no
   evidence: Unconfirmed. The search model's word is never evidence. (`research/sellers.py::classify_seller`)
7. **Duplicates.** The same listing seen on several directory pages is one offer with extra links (R40);
   the same company (name plus city) on several platforms keeps its cheapest listing, the rest become
   extra links. (`nodes.py::_same_listing`, `research/sellers.py::merge_by_manufacturer`)
8. **Older listing.** A page date older than `OFFER_MAX_AGE_DAYS` (180) gives "Older listing", not in range.

### Sanity rules (check_sanity)

Prices are taken at the requested quantity. (`research/sanity.py::apply_sanity`)

- **Unusually low:** below `UNUSUALLY_LOW_FACTOR` (0.6) x the cost estimate's low bound. A warning only.
- **Unusually high against cost (R29):** above `OUTLIER_FACTOR` (3) x the cost estimate's high bound: out of
  range. When the cost has low confidence it is a warning only (R37), unless the price is more than 10 x
  that band, i.e. 30 x the cost high (R40: a box price shown per piece), which is always cut.
- **Median outlier:** with three or more in-range offers, above 3 x their median: out of range, kept in
  the list.
- **Cost-free cut (R40):** with two or more in-range offers, anything above 30 x the cheapest believable
  in-range price is cut.
- **Cost above market (R33):** if the cost estimate is above the lowest displayed price, the cost becomes low
  confidence with the note "Estimated making cost is above the lowest market price; treat it as rough".

### Cost rules (cost branch)

- Only materials are searched; process steps always use the planner's estimate (R32).
- A cited material price must be one per-kg rupee number attached to its unit in the quote, with no other
  amount or arithmetic in the quote, and the page must name this material (not another grade of the same
  family) near it (R38). Otherwise the line is an estimate, labelled "estimate, no source".
  (`nodes.py::_per_kg`, `::_cited_price`, `::_right_material`)
- Confidence: High when every line is cited; Medium when every material is cited; Low when any material is
  an estimate. (`research/cost.py::compute_cost`)

### Range rule (shown on the card)

Computed by the browser and by `research/tiers.py::purchase_range`, tested on both sides with
`shared/calculator_cases.json`:

- Only in-range offers count. Confirmed manufacturers first; if none, unconfirmed sellers with the label
  "Unconfirmed sellers only".
- Each offer's price is its tier with the highest minimum quantity not above the requested quantity.
  Offers whose MOQ is above the quantity are out; if that removes every offer, each offer's lowest-MOQ
  tier is used and the card says "All manufacturers need a larger order".
- Lowest and highest are the min and max of those prices (ties by id). Totals add GST % and freight.

## 3. Part research (Split and research)

`RunService.split` takes the parts the intake listed for a splittable item. For each part, in parallel
under the same semaphore, it builds a part spec (`research/spec.py::build_part_spec`: part name, its
typical material as a search term, and the parent's gauge for needle or cannula parts, else the parent's
capacity, as the only `must_match`; quantity = parent quantity x `count_per_unit`) and runs the research
graph in part mode (offer branch only, every verification rule identical). The cheapest in-range offer
per part is kept; the parts total is the sum of unit price x `count_per_unit`, or none when a part has no
manufacturer. The summary compares it with the lowest finished-product price; assembly and sterilisation
are not included. One failing part never fails the split.

## 4. Budgets, progress and failure handling

Per item (settings, `research/budget.py`); exceeding one stops that branch cleanly and adds a note such as
"Stopped early: page budget reached":

| Budget | Default | Branch |
|---|---|---|
| `BUDGET_TAVILY_CALLS` | 12 | offers |
| `BUDGET_WEB_SEARCH_CALLS` | 2 | offers |
| `BUDGET_PAGES` | 30 | offers |
| `BUDGET_LLM_CALLS` | 30 | offers (extraction, broaden) |
| `BUDGET_COST_SEARCH_CALLS` | 6 | cost |
| `BUDGET_COST_PAGES` | 8 | cost |
| `BUDGET_COST_LLM_CALLS` | 8 | cost |
| `ITEM_TIMEOUT_SECONDS` | 180 | both; the graph stops starting new work after it ("Stopped early: time limit reached") |

- Every external call is retried once on a transient failure (Tavily 429 or 5xx, timeouts); a second
  failure becomes a step-log note and the run continues (`nodes.py::_retry_once`). OpenAI quota errors
  are not retried.
- Nodes write short events to `run_event`; `GET /api/research/{id}/events` streams them over SSE.
- Cancel sets a flag that every node checks before working; the result returned after a cancel is
  discarded. On server start, queued or running runs (and running splits) become `interrupted` and can be
  retried.
