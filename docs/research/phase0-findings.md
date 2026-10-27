# Phase 0 findings: OpenAI web search and B2B platform fetchability

Run on 2026-10-26. Scripts: `spikes/openai_web_search.py`, `spikes/fetch_platforms.py`. Fixtures: `backend/tests/fixtures/pages/`.

## 1. OpenAI `web_search` with structured output

- Model used: `gpt-4.1` (no OPENAI_MODEL set; fell back to OPENAI_VISION_MODEL). Key accepted, no quota error.
- `client.responses.parse(model, tools=[web_search, user_location IN], text_format=Hits)` WORKS: it returned a parsed list of `{url, title, seller}`.
- Caveats:
  - Reliability is weak. In one run the `url` field held the page title instead of a URL (`url='Nihal PP 2 ml Disposable Syringe With Needle - ExportersIndia'`). In another run the URLs were correct. Do not trust `text_format` URLs without validation.
  - In parse mode our loop over `message.content[].annotations` found 0 `url_citation` items, so citations were not surfaced there.
  - Plain `responses.create` with `web_search` returns output `['web_search_call', 'message']` with 6 `url_citation` annotations (tradeindia, isconsurgicals, vivansurgical, a bhu.ac.in price-list PDF, sastasundar, apollopharmacy). All carry a `?utm_source=openai` suffix: strip it.
- Recommendation: use the fallback as the primary path. Call `web_search` without `text_format`, take URLs from `url_citation` annotations (strip `utm_source`, validate with a URL parser), and use a second `parse` call on the text only if seller names are needed. Citations are real fetched sources, which is what verification needs.
- Results mix manufacturers, traders, retail pharmacies and PDFs, so seller classification and the denylist stay necessary.

## 2. Fetchability (direct httpx vs Tavily /extract)

Direct fetch used `HTTP_USER_AGENT` from `.env`, timeout 15 s, redirects followed. All 11 pages returned HTTP 200 directly. "price" = a rupee marker (`₹`, `Rs`, `INR`) present in the body.

| Platform | Page | Direct | Extract (size, price?) |
|---|---|---|---|
| IndiaMART | listing `dir.indiamart.com/impcat/syringe-without-needle.html` | 200, 220 KB, price yes | 20 KB, yes |
| IndiaMART | listing `.../impcat/medical-surgical-syringes.html` | 200, 301 KB, yes | 19 KB, yes |
| IndiaMART | product `proddetail/...nitrile-examination-gloves...` | 200, 58 KB, yes | 8 KB, yes |
| IndiaMART | product `proddetail/iv-cannula-20g-pink-...` | 200, 43 KB, yes | 1 KB, yes (nearly empty) |
| TradeIndia | city listing `/anantnag/disposable-syringe-city-180144.html` | 200, 425 KB, yes | 32 KB, yes |
| TradeIndia | `/manufacturers/syringe-needles.html` | 200, 759 KB, yes | 57 KB, yes |
| TradeIndia | product `/products/pvc-urine-collection-bag-...` | 200, 270 KB, yes | 10 KB, yes |
| ExportersIndia | product-detail `2-ml-disposable-syringe-without-needle` | 200, 212 KB, yes | 16 KB, NO price |
| ExportersIndia | listing `/indian-suppliers/disposable-syringes.htm` | 200, 570 KB, yes | 101 KB, yes |
| Manufacturer | `unitedsurgical.in/disposable-syringes.html` (IndiaMART-powered mini site) | 200, 688 KB, yes | 51 KB, yes |
| Manufacturer | `banshimedicare.com/gloves/nitrile-gloves-manufacturer` | 200, 252 KB, NO price | 3 KB, no |

Conclusion: direct httpx with a browser-like UA works on all three platforms right now (no bot wall seen). Tavily extract also succeeds but is lossy (drops seller-type and some price fields; the ExportersIndia detail lost its price, the IndiaMART product page was reduced to 1 KB). Use direct fetch first, Tavily extract as fallback only. Pages are large (up to 760 KB raw), so keep `page_fetch_max_bytes` at 1.5 MB or more.

A PDF (a UK gov document) was returned by Tavily search for a manufacturer query; filter `.pdf` URLs.

## 3. Real text formats (feed Task 11 parser tests)

IndiaMART product page:
- Title: `Black Nitrile Examination Gloves Powder Free ... at ₹ 150/box | Powder Free Gloves in Ahmedabad`
- Body: `₹ 150/ Box Enter Quantity Pair Submit Requirement Size 9 Inches Material Nitrile Type Powder Free`
- Seller type: `Nature of business Trader - Retailer` and `Nature of business Wholesaler/Distributor` (GST section). Badges: `TrustSEAL`, `Verified`, `GST`, `Payment Protected 5 yrs`.

IndiaMART listing cards:
- `10ml Blue Oral Dosing Syringe Without Needle ₹ 9.10 / Piece Contact Supplier Call`
- `Polypropylene Luer Disposable Unsterile Syringe ₹ 1 / Piece`
- `Disposable Medical Oral Syringe ₹ 1.50/Piece I & S Traders`
- Seller line: `Neelkanth Polymer Industries Navi Mumbai · 9 yrs TrustSEAL 90% Response Rate`. Cards often carry no MOQ.

TradeIndia product page:
- `Price: 15 INR / Piece Get Latest Price Minimum Order Quantity : 100 Piece In Stock`
- `Price: 100 INR MOQ - 500 Piece/Pieces Pratap Soap Factory Kanpur, Uttar Pradesh`
- Title: `... at 15.00 INR at Best Price in Kanpur | Km Traders`

TradeIndia listing:
- `Price: 1.75 INR/Piece Get Best Quote MOQ 2000 Piece/Pieces`
- `Price: 2.25 INR/Unit Get Best Quote MOQ 3000000 Unit/Units`
- `Price: 1600 INR Get Best Quote MOQ 1 Pack of 1000` (pack-based MOQ, not pieces)
- `1.75 INR (Approx.)` in a currency table
- Seller type: `Business Type: Supplier | Trading Company`, `Business Type: Supplier | Exporter`, `Business Type: Distributor | Supplier`.

ExportersIndia:
- `Price: 1.75 - 2.50 / Piece Get Latest Price Minimum Order Quantity : 1000 Piece Sold By : Medmech Healthcare Private Limited`
- Listing: `2 Ml Disposable Syringe Without Needle ₹ 1.75 - ₹ 2.50 / Piece Get Quote` (price range with ₹ on both ends)
- `Price: 6.50 - 9 / Piece MOQ : 10000 Piece` (range, no currency symbol)
- Seller type: `Business Type Manufacturer Exporter Wholesaler Retailer` (multi-valued), `Supply Type Exporter, Supplier, Trader`, `Business Type Manufacturer / Exporter / Supplier / Distributor / Importer / Trader`. Badges: `Verified`, `GST Trusted 6 Years`, `Platinum Plus`.

IndiaMART-powered manufacturer mini site (unitedsurgical.in):
- `Sterile Hypodermic Syringe Get Best Quote Rs 1.53  / Piece Price on Request Minimum Order Quantity: 2000 Piece`
- `5ml Unisafe Syringe Rs 155  / Box ... Minimum Order Quantity: 100 Box`
- Title: `... Exporter & Trader - Wholesaler / Distributor from Ghaziabad`. Note "Price on Request" text sits next to a visible price.

Parser takeaways: price markers vary (`₹ 150/box`, `Rs 1.53 / Piece`, `Price: 15 INR / Piece`, bare `Price: 6.50 - 9 / Piece`); ranges are common; the basis is `/Piece`, `/Box`, `/Unit`, `/Pack`; MOQ labels are `MOQ`, `MOQ -`, `Minimum Order Quantity :`; pack-based MOQ exists. "Manufacturer" appears in the page title of most pages regardless of the seller's real type, so seller type must come from the structured field (`Nature of business`, `Business Type`), never from the title.

## 4. Settings defaults to consider

- `page_fetch_max_bytes`: keep 1_500_000 (raw pages up to 760 KB).
- `http_user_agent`: a browser-style UA worked on all three platforms; keep it. `respect_robots=True` was not tested here and may block listing paths; verify in Task 12.
- Fetch order: direct first, Tavily extract as fallback (extract is lossy).
- Prefer `create` + citations over `parse` for web_search; strip `utm_source=openai` from URLs.
- Model: `gpt-4.1` works with `web_search`; set `OPENAI_MODEL` in `.env` explicitly.
- Filter `.pdf` and retail pharmacy domains from candidates.

## 5. Fixtures

`backend/tests/fixtures/pages/`: `indiamart_1..4`, `tradeindia_1..3`, `exportersindia_1..2`, `manufacturer_1..2`. Scripts (except JSON-LD) and styles stripped, each under 300 KB. `manufacturer_1` was truncated at 290,000 characters.

## Intake live check

Task 10, `POST /api/research` with `text` only, real OpenAI calls, server on port 8016. All 5 returned one in-scope consumable and no screening message.

| Product text | Items | Questions asked (keys) |
|---|---|---|
| 2 mL syringe with needle, 50,000 nos | 1 | quantity, sterility, needle_gauge, needle_length, type |
| 3-ply surgical mask, 1 lakh pieces | 1 | quantity, ear_loop_type, size, sterility |
| nitrile examination gloves (M, powder-free), 500 boxes | 1 | quantity, box_size, sterility, brand, unit_basis |
| IV cannula 20G, 10,000 pcs | 1 | quantity, material, sterility, with_injection_port |
| urine bag 2000 mL, 2000 nos | 1 | quantity, sterility, valve_type, tube_length |

Notes: quantity was prefilled from the text for all but the gloves (boxes need a pieces-per-box basis, so quantity and unit_basis start blank). Questions with no stated answer start unanswered and show in `answer_errors`. Image-only and image plus text were not run live here (covered by FakeLLM tests).
