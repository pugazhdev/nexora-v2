# API

Base URL: `http://localhost:8015/api` (the Vite dev server on 5173 proxies `/api` to it). All routes are in
`backend/app/api/routes.py`. JSON in and out, except `POST /research` (multipart) and the event stream (SSE).
Timestamps are UTC ISO 8601 with a `Z`. Money values are decimal strings in INR (for example `"1.75"`).
The examples below are real responses from the local database, shortened (lists cut to one or two
entries).

## Errors

Every error has the same shape:

```json
{"error": {"code": "not_found", "message": "Research not found.", "details": {}}}
```

| HTTP | code | When |
|---|---|---|
| 400 | `bad_request` | Validation failures (no input, text too long, missing answers; `details.items` maps item id to field errors) |
| 404 | `not_found` | Unknown research, item, run or route |
| 409 | `conflict` | Already running, out-of-scope item selected, retry or split not allowed in this state |
| 413 / 415 / 422 | `image_too_large` / `unsupported_image` / `invalid_image` | Image validation |
| 429 | `rate_limited` | Local rate limit (`RATE_LIMIT_PER_MINUTE`, `ANALYSE_RATE_LIMIT_PER_MINUTE`) |
| 429 | `llm_quota` | OpenAI rate limit or quota exceeded |
| 502 | `llm_error`, `llm_auth`, `llm_bad_response`, `llm_rejected_input`, `search_failed` | Provider failures |
| 503 | `config_missing` | "Set OPENAI_API_KEY, OPENAI_MODEL and OPENAI_VISION_MODEL in backend/.env" |
| 503 | `not_ready` | Database not ready (`/ready`) |
| 504 | `llm_timeout` | OpenAI timed out |
| 500 | `internal_error` | Anything unexpected (no internals are leaked) |

## Health

### `GET /health`

```json
{"status": "ok"}
```

### `GET /ready`

`{"status": "ready"}`, or 503 `not_ready` when the database cannot be queried.

## Research

### `POST /research` (Analyse)

Multipart form: `image` (optional file: JPEG, PNG or WebP) and/or `text` (optional string, at most
`MAX_TEXT_CHARS`). At least one is required. Runs the intake graph inline (about 5 to 20 s) and returns
the new research. `message` is the screening note ("The photo is too blurry to read...", "Showing the
first 10 items") or null. Rate limited by `ANALYSE_RATE_LIMIT_PER_MINUTE`.

```bash
curl -F "text=2 mL disposable syringe with needle, 50,000 nos" http://localhost:8015/api/research
```

Response: the same shape as `GET /research/{id}` below, with `latest_run: null` on every item.

### `GET /research?limit=20&offset=0`

History, newest first. `limit` is clamped to 1 to 100. `item_count` counts in-scope items.

```json
[
  {"id": "c4437eb9252242f2a7e859aa9b2ade8c", "title": "urine bag 2000 mL",
   "created_at": "2026-10-26T17:05:34.605729Z", "status": "done", "item_count": 1}
]
```

`status` is derived: `draft` (no run yet), `researching` (a selected item is queued or running), `done`.

### `GET /research/{id}`

Full research with items, questions, answers and the latest run of each item.

```json
{
  "id": "05d7a6856a164d92b0beb389ed370776",
  "title": "2 mL syringe with needle",
  "created_at": "2026-10-26T16:11:31.832888Z",
  "image_path": null,
  "status": "draft",
  "message": null,
  "items": [
    {
      "id": "2965a07ca34e4ac69ab3f8b54b54781b",
      "position": 0,
      "name": "2 mL syringe with needle",
      "category": "consumable",
      "in_scope": true,
      "scope_reason": null,
      "selected": true,
      "known_attributes": [
        {"key": "capacity", "label": "Capacity", "value": "2 mL", "evidence": "stated in text"}
      ],
      "questions": [
        {"key": "quantity", "label": "Quantity", "help": null, "kind": "number", "options": [],
         "unit": "units", "min": 1.0, "max": null, "default": 50000.0, "required": true, "price_relevant": false},
        {"key": "sterility", "label": "Sterile or non-sterile?", "help": null, "kind": "single",
         "options": [{"value": "sterile", "label": "Sterile"}, {"value": "non-sterile", "label": "Non-sterile"}],
         "unit": null, "min": null, "max": null, "default": null, "required": true, "price_relevant": true}
      ],
      "answers": {"quantity": 50000.0},
      "answer_errors": {"sterility": "Sterile or non-sterile? is required"},
      "splittable": true,
      "parts": [
        {"name": "syringe", "typical_material": "plastic", "count_per_unit": 1},
        {"name": "needle", "typical_material": "stainless steel", "count_per_unit": 1}
      ],
      "image_region_hint": "",
      "latest_run": null
    }
  ]
}
```

`category` is one of `consumable`, `medicine`, `equipment`, `unclear`. Medicines and equipment come back
with `in_scope: false`, `selected: false` and a `scope_reason` ("Medicines are out of scope", "Equipment,
not a consumable"). Question `kind` is one of `single`, `multi`, `number`, `text`, `boolean`.

`latest_run`, once research has run (from the Run 5 syringe):

```json
{
  "id": "92dfeaf4f2c24992b860a9f5a7e819b2",
  "item_id": "a55c9e3dc2bb46b28a4281f71b085853",
  "answers": {"quantity": 10000, "needle_gauge": "23G", "sterility": "sterile"},
  "spec": {
    "name": "2 mL syringe with needle",
    "attributes": {"needle_gauge": "23G", "sterility": "Sterile", "syringe_volume": "2 mL"},
    "quantity": 10000,
    "title": "2 mL syringe with needle, 23G, Sterile, 2 mL",
    "must_match": ["needle_gauge", "sterility"],
    "type_terms": [],
    "primary_key": "syringe_volume"
  },
  "status": "done",
  "result": {
    "spec_title": "2 mL syringe with needle, 23G, Sterile, 2 mL",
    "quantity": 10000,
    "cost": {
      "per_unit": "1.25", "low": "1.14", "high": "1.38", "confidence": "low",
      "lines": [
        {"label": "barrel", "amount": "0.28",
         "basis": "average weight for 2ml disposable syringe barrels from manufacturer specs",
         "source_ids": [1], "estimated": false,
         "quote": "PP (Polypropylene) trades at ₹105-120 per kg currently."}
      ],
      "sources": [{"id": 1, "url": "https://www.ofbusiness.com/category/polymers-packaging", "title": "polypropylene"}]
    },
    "offers": [
      {
        "id": "890cd78fff3b43cd",
        "manufacturer": "Medmech Healthcare Private Limited",
        "city": null, "state": null,
        "platform": "ExportersIndia",
        "url": "https://www.exportersindia.com/agra/syringes.htm",
        "classification": "manufacturer",
        "tiers": [{"min_qty": 1, "unit_price": "1.75"}],
        "moq": null,
        "in_range": true,
        "flags": ["spec_partly_confirmed"],
        "extra_links": ["https://www.exportersindia.com/valsad/disposable-syringes.htm"],
        "price_quote": "₹ 1.75 - ₹ 2.50 / Piece",
        "spec_match": "match",
        "observed_at": null,
        "gst_rate_pct": null
      }
    ],
    "gst": {"rate_pct": "12", "source_url": "https://www.exportersindia.com/kolkata/syringes.htm"},
    "notes": ["Could not read nihalhealthcare.com"],
    "queries": ["2 mL syringe with 23G needle sterile manufacturer India"]
  },
  "error": null,
  "split_status": null,
  "split": null,
  "split_error": null,
  "retail": {
    "rows": [
      {"retailer": "Tata 1mg", "title": "Dispovan 2 ml Syringe with Needle", "url": "https://www.1mg.com/otc/...",
       "pack_size": 10, "unit_price": "15.00", "pack_price": "150", "price_quote": "₹150"}
    ],
    "notes": [],
    "queries": ["2 mL syringe with needle, 23G, Sterile, 2 mL price", "2 mL syringe with needle, 23G, Sterile, 2 mL buy online"]
  },
  "created_at": "2026-10-26T18:10:34.281483Z",
  "started_at": "2026-10-26T18:10:34.356084Z",
  "finished_at": "2026-10-26T18:11:24.587823Z"
}
```

- Run `status`: `queued`, `researching`, `done`, `failed`, `cancelled`, `interrupted`.
- Offer `classification`: `manufacturer`, `unconfirmed`, `excluded`. `in_range` says whether the offer may
  form the lowest/highest range. The range itself is computed by the client (and by
  `app.research.tiers.purchase_range`) at the requested quantity.
- Offer `flags`: `price_on_request`, `basis_unclear`, `incl_gst_rate_unknown`, `spec_unstated`,
  `spec_partly_confirmed`, `ambiguous_variants`, `older_listing`, `unusually_low`, `unusually_high`,
  `outlier`, `conflicting_seller_type`.
- `retail`: retail prices for reference (Tata 1mg, PharmEasy, Netmeds, Apollo Pharmacy, MedPlus, Amazon
  India, Flipkart), stored apart from `result` and never used by the range, cost or directory. Up to 5 rows,
  one per retailer, lowest `unit_price` first; `unit_price` is `pack_price / pack_size` and includes retailer
  margin and GST. `null` while the lookup runs (it runs beside the research of the item, never for parts)
  and on runs made before this field existed. Stops and failures are `notes` starting with "Retail:".
- Cost `confidence`: `high`, `medium`, `low`. The last cost line is always "Overhead and scrap".
  `estimated: true` lines have no source.

### `PATCH /research/{id}/items/{item_id}`

Select or unselect an item and/or replace its answers. Returns the item JSON with fresh `answer_errors`.
Selecting an out-of-scope item is 409. Editing answers after a finished run never changes that run; the
next Start creates a new run.

```json
{"selected": true, "answers": {"quantity": 10000, "sterility": "sterile"}}
```

### `POST /research/{id}/start`

Validates answers of every selected item and queues them (one after another). 400 with
`details.items` when answers are missing or invalid, 400 when nothing is selected, 409 when already
running, 503 `config_missing` without OpenAI settings.

```json
{"run_ids": ["92dfeaf4f2c24992b860a9f5a7e819b2"]}
```

### `POST /research/{id}/cancel`

Cancels queued and running items of the research (the current node finishes, the partial result is
discarded, status `cancelled`). Returns the research JSON.

### `DELETE /research/{id}`

Deletes the research with its items, runs, run events, listings and the uploaded image file. Manufacturer
rows are kept (their `listing_count` drops). 204 with no body, 404 for an unknown id, 409 `conflict`
("Cancel the research before deleting it.") while an item is queued or researching or a split is running.

### `GET /research/{id}/events?after=0` (SSE)

Server-sent events for the research. Resume with `?after=<last id>` or the `Last-Event-ID` header. Two
event types; the stream closes about 2 s after every selected item is in a terminal state; a
`: keepalive` comment is sent every 15 s.

```
id: 812
event: step
data: {"id": 812, "run_id": "92dfeaf4...", "at": "2026-10-26T18:10:41.102Z", "phase": "search", "level": "info", "message": "Found 23 listings (IndiaMART 12, TradeIndia 6, maker sites 5)", "item_id": "a55c9e3d..."}

id: 812
event: status
data: {"status": "researching", "items": [{"item_id": "a55c9e3d...", "run_id": "92dfeaf4...", "status": "researching", "error": null}]}
```

`phase` is one of `plan`, `search`, `read`, `verify`, `split`, `retail`; `level` is `info` or `warn`.

## Items and runs

### `POST /items/{item_id}/retry`

Re-runs an item whose latest run is `failed`, `interrupted` or `cancelled` (409 otherwise).

```json
{"run_id": "9cc41f1dbf394219ba1ecb70de0408c7"}
```

### `POST /items/{item_id}/split`

Starts part research for a splittable item whose latest run is `done`. 409 when not splittable, not
done, or a split is already running. Progress goes to the same event stream (`phase: "split"`); the
result lands on the latest run as `split_status` and `split`.

```json
{"status": "running"}
```

`split` when finished:

```json
{
  "parts": [
    {"part": "Needle", "count_per_unit": 1, "offer": {"...": "an Offer, the cheapest in range"}, "notes": []},
    {"part": "Syringe barrel", "count_per_unit": 1, "offer": null, "notes": ["Stopped early: page budget reached"]}
  ],
  "parts_total": null,
  "finished_lowest": "1.75",
  "complete": false
}
```

`parts_total` is the sum of each part's lowest unit price times `count_per_unit`, or null when any part
has no manufacturer (`complete: false`).

### `GET /items/{item_id}/runs`

Every run of an item, newest first (History uses it to open earlier runs).

```json
[
  {"id": "92dfeaf4f2c24992b860a9f5a7e819b2", "status": "done",
   "started_at": "2026-10-26T18:10:34.356084Z", "finished_at": "2026-10-26T18:11:24.587823Z"}
]
```

### `GET /runs/{run_id}`

One run row, same shape as `latest_run` above.

## Manufacturers

### `GET /manufacturers?starred=&q=&limit=50&offset=0`

Directory of every manufacturer or unconfirmed seller seen in research (excluded traders are never
stored). `starred=true` gives the Shortlist; `q` filters by name; `limit` 1 to 200.

```json
[
  {"id": "0363937d47a44303829a8102be57fd1b", "name": "Amkay Products Limited", "city": "Vasai",
   "state": null, "website": null, "platforms": ["TradeIndia"], "listing_count": 2,
   "last_seen": "2026-10-26T18:13:41.404499Z", "starred": false}
]
```

### `GET /manufacturers/count`

```json
{"total": 255, "starred": 0}
```

### `PATCH /manufacturers/{id}`

```json
{"starred": true}
```

Returns the manufacturer JSON.

## Settings

### `GET /settings`

Read-only configuration status. Never returns key values.

```json
{
  "openai_configured": true,
  "tavily_configured": true,
  "model": "gpt-4.1",
  "vision_model": "gpt-4.1",
  "budgets": {
    "budget_tavily_calls": 12, "budget_web_search_calls": 2, "budget_pages": 30, "budget_llm_calls": 30,
    "budget_cost_search_calls": 6, "budget_cost_pages": 8, "budget_cost_llm_calls": 8,
    "budget_retail_search_calls": 4, "budget_retail_pages": 8, "budget_retail_llm_calls": 8
  },
  "research_concurrency": 2,
  "denylist": ["1mg.com", "amazon.com", "amazon.in", "apollopharmacy.in", "flipkart.com"]
}
```
