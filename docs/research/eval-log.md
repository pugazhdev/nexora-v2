# Live evaluation log

## 2026-10-26, Phase 3 (offer branch), Task 18 end-to-end run

How it was run: server `uvicorn app.main:app_factory --factory --port 8016` on the real `backend/.env`
(OpenAI `gpt-4.1`, Tavily configured). For each product: `POST /api/research` (text), `PATCH` the
answers below, `POST /start`, poll `GET /api/research/{id}` until done. Lowest/highest computed with
`app.research.tiers.purchase_range` (the same rule the UI uses) at the requested quantity. Every
lowest/highest URL was then fetched with httpx (browser UA), converted with `html_to_text`, and
checked for the unit price and the exact `price_quote`. Research concurrency 2; all five runs
finished (status `done`) in 41 to 69 s each, no failures, no timeouts. SSE was also checked with
curl against a live research (status event received while queued).

| Product | Answers given | Offers (mfr / unconfirmed / excluded) | In range | Lowest | Highest |
|---|---|---|---|---|---|
| 2 mL syringe with needle | qty 10000, needle 23G, sterile | 31 (3 / 19 / 9) | 1 | Rs 60.00/piece, Welox Pharma Pvt Ltd, Surat, [TradeIndia](https://www.tradeindia.com/manufacturers/disposable-needles.html) | same offer |
| 3-ply surgical mask | qty 10000, polypropylene, non-sterile, earloop | 36 (6 / 28 / 2) | 0 | none | none |
| Nitrile examination gloves, M, powder-free | qty 10000, non-sterile, 100 per box | 11 (3 / 3 / 5) | 0 | none | none |
| IV cannula 20G | qty 10000, sterile, PTFE, with injection port | 9 (1 / 8 / 0) | 0 | none | none |
| Urine bag 2000 mL | qty 10000, sterile, T-tap, tube 90 cm | 28 (8 / 15 / 5) | 0 | none | none |

### Links checked

- Syringe lowest = highest: `https://www.tradeindia.com/manufacturers/disposable-needles.html`.
  HTTP 200. The page contains "Price: 60 INR/Piece" and the seller block "Welox Pharma Private
  Limited | Surat | Business Type: Manufacturer" right after it. **The number matches the page, but
  the listing is the wrong product**: "Romsons Disposable Needle - 23G x 1Inch Pack of 100
  (SS-6088)", a needle, not a 2 mL syringe with needle. It was marked `spec_match: match` because
  23G matched and nothing contradicted "sterile". So the shown range is wrong even though its
  number is real.
- No other product produced a lowest/highest, so there were no other links to check.

### Issues found (Phase 3 is NOT done)

1. **Answered detail questions empty the range.** Every answered `price_relevant` question goes into
   `must_match`. Most B2B listings do not state sterility, material, tube length or pieces per box,
   so they are `spec_unstated` and excluded from the range. Examples kept out: "2 Ml Disposable
   Syringe With Needles, Price: 1.17 INR/Piece, MOQ 10000" (Wellcare Healthcare, same TradeIndia
   page), "3 ply face mask Rs 0.50/piece" (VS Prime Enterprise, ExportersIndia), "IV cannula
   Rs 4.25 to 4.60/piece" (Hi Tech Medicare Devices, ExportersIndia), "urine collection bag 12 to 25
   INR/piece" (Advin Health Care, TradeIndia). Needs a decision: probably only contradictions
   (mismatch) should exclude, with unstated attributes shown as a caveat, or must_match limited to
   the item's defining attributes (capacity, gauge, size).
2. **Wrong product passes spec match** (syringe case above): a needle-only listing matched a
   "syringe with needle" spec. The product type itself is not checked against the title.
3. **Boolean answer renders as the question label.** IV cannula spec attribute
   `with_injection_port` became "With injection port?" (`spec._display` returns `q["label"]` for
   `True`), and that text went into the search queries and the spec title.
4. Budgets: mask, cannula and urine bag stopped on the AI extraction budget (30) and page budget;
   gloves stopped on search and page budgets. Category pages with many listings burn the budget.
5. `www.justdial.com`, `demo.buyersgate.in` and `animeal.in` could not be read (logged as notes).

### Notes the runs produced

- Syringe: "Could not read www.justdial.com", "Could not read animeal.in".
- Mask: "Stopped early: AI extraction budget reached", "Stopped early: page budget reached".
- Gloves: "Could not read www.justdial.com", "Could not read demo.buyersgate.in", "Stopped early:
  search budget reached", "Stopped early: page budget reached".
- IV cannula: "Could not read www.justdial.com", "Stopped early: AI extraction budget reached",
  "Stopped early: page budget reached".
- Urine bag: "Stopped early: AI extraction budget reached", "Stopped early: page budget reached".

### Queries used (products with no range)

- Mask: "3-ply surgical mask Polypropylene Non-sterile Earloop manufacturer India"; "3-ply surgical
  mask Polypropylene Earloop Non-sterile IndiaMART"; "Polypropylene 3-ply surgical face mask
  non-sterile earloop TradeIndia"; "Earloop 3-ply mask non-sterile Polypropylene ExportersIndia";
  "3-ply polypropylene earloop mask non-sterile manufacturer price per piece"; "3-ply surgical mask
  earloop non-sterile buy online India"; "3 layer polypropylene face mask non-sterile manufacturer
  India"; "Non-sterile earloop 3-ply surgical mask manufacturer with price India"; plus 2 OpenAI web
  search prompts.
- Gloves: 12 Tavily queries such as "nitrile examination gloves non-sterile 100 gloves nitrile M
  powder-free manufacturer India", "nitrile exam gloves M non-sterile powder-free 100 pcs box
  IndiaMART", "non sterile nitrile gloves M 100 pcs per box supplier price list India" (one broaden
  round), plus 2 web search prompts.
- IV cannula: "IV cannula 20G sterile PTFE with injection port manufacturer India", "20 gauge PTFE
  intravenous cannula with injection port supplier India", "IndiaMART IV cannula 20G sterile PTFE
  with injection port", and 5 more, plus 2 web search prompts.
- Urine bag: "urine bag 2000 mL T-tap 90 cm Sterile manufacturer", "urine collection bag sterile
  T-tap 90 cm 2000 ml India", "Sterile urine bag 2000ml T-tap tube 90cm site:indiamart.com", and 5
  more, plus 2 web search prompts.

## Run 2, 2026-10-26, after Task 18b (Ruling R24: type gate, primary attribute, size lists, boolean labels)

How it was run: same server setup and `.env` (port 8016). The five Run 1 researches were started again
with `POST /api/research/{id}/start`, so the questions and answers are exactly the Run 1 ones. All five
finished `done` in 35 to 52 s each, no failures. Lowest/highest from `purchase_range` at qty 10000;
every lowest/highest URL fetched again (httpx, browser UA, `html_to_text`), the `price_quote` searched
on the page, and the listing text around it read by hand for product type and variant.

| Product | Answers given | Offers (mfr / unconfirmed / excluded) | In range | Lowest | Highest | Right product/variant? |
|---|---|---|---|---|---|---|
| 2 mL syringe with needle | qty 10000, needle 23G, sterile | 27 (1 / 20 / 6) | 2 | Rs 4.00/piece, Thyrocare Technologies Limited, Thane, [IndiaMART](https://www.indiamart.com/proddetail/2ml-syringe-needle-2854163051930.html) | Rs 400.00/piece, Newlife Medicare Pvt Ltd, Nagpur, [IndiaMART](https://dir.indiamart.com/nagpur/medical-syringes.html?biz=40) | Lowest: yes ("2ml Syringe Needle, 23 G", BD, sterilised). Highest: right product ("BD Emerald 2ml Syringe with 23G Needle") but the page's "Rs 400 / Piece" next to "Packaging Size 1 x 100" is almost certainly a box price; the number is on the page, the unit is not credible |
| 3-ply surgical mask | qty 10000, polypropylene, non-sterile, earloop | 17 (1 / 14 / 2) | 2 | Rs 0.75/piece, Shubh Dispo Care, New Delhi, [maker site](https://www.shubhdispocare.com/face-mask-manufacturer-in-delhi.html) | Rs 10.00/piece, Shivay Surgical, Kadi, [TradeIndia](https://www.tradeindia.com/manufacturers/surgical-mask.html?nob=supplier) | Lowest: yes (3 ply surgical mask, polypropylene, ear loop). Highest: mask yes, variant not confirmed: title says "100% Medical Grade Cotton", no ply, no ear loop, no sterility on that listing, yet it had no flags |
| Nitrile examination gloves, M, powder-free | qty 10000, non-sterile, 100 per box | 14 (2 / 8 / 4) | 2 | Rs 1.45/piece, Safe & Fresh Products Pvt Ltd, Delhi, [TradeIndia](https://www.tradeindia.com/manufacturers/nitrile-exam-gloves.html) | Rs 6.60/piece (Rs 660 / box of 100), Akshyata Will Pharmaceuticals, Delhi, [ExportersIndia](https://www.exportersindia.com/indian-suppliers/nitrile-exam-gloves.htm) | Both yes (nitrile examination gloves; lowest lists sizes XS to XL, highest is Medium, box of 100, non-sterile). Lowest page shows "MOQ100000 Piece/Pieces", above the 10000 asked, but the offer had no MOQ |
| IV cannula 20G | qty 10000, sterile, PTFE, with injection port | 8 (1 / 4 / 3) | 2 | Rs 4.65/piece, Cruzine Healthcare Pvt Ltd, Surat, [IndiaMART](https://dir.indiamart.com/impcat/iv-cannula.html) | Rs 4.80/piece, Hagnosmed Enterprises, Lucknow, same page | **No.** Cruzine's Rs 4.65 listing on the page is "Iv Cannula 18, 18G, With port" (wrong gauge). Hagnosmed's only listing on the refetched page is "24g Iv Cannula, With port, Rs 5.80"; "Rs 4.80" was not found on the page any more |
| Urine bag 2000 mL | qty 10000, sterile, T-tap, tube 90 cm | 35 (8 / 22 / 5) | 8 | Rs 9.00/piece, Royo Scientific Pvt Ltd, Dungarpur, [TradeIndia](https://www.tradeindia.com/dhar/disposable-urine-bag-city-189841.html) | Rs 43.00/piece, Royo Scientific Pvt Ltd, Dungarpur, [TradeIndia](https://www.tradeindia.com/pithampur/urine-bags-city-212440.html) | Both yes (urine collection bag / urine bag, 2000 ml); T-tap, tube length and sterility unstated, flagged spec_partly_confirmed |

Every lowest/highest `price_quote` except Hagnosmed's was found on the refetched page.

### What R24 fixed

- Ranges are no longer empty: every product now has a range (2 to 8 offers in range), mostly offers
  flagged `spec_partly_confirmed` because a secondary detail is unstated.
- The needle-only listing (Run 1 syringe range) is gone; no in-range offer is a different product type.
- Boolean answers render as "With injection port" (no question text) in the spec title.

### Issues still open (honest list; not tuned here)

1. **Wrong variant still reaches the range on category pages (IV cannula).** The likely cause:
   extracted attribute values are verified anywhere on the page (`quote_in_page`), not inside the
   listing's own block. On a category page "20G", "Earloop" or "Non-sterile" appear in some other
   listing, so a listing whose own text says 18G (or says nothing) can still get a verified `20G`
   attribute and a gauge `match`. The same explains the cotton mask with no flags. Fix to consider:
   verify attribute values (and the product title) near the verified price quote, as seller-type
   quotes already are.
2. **Defining attributes from intake are not always in `must_match`.** `build_spec` adds known
   attributes only when the key is exactly one of capacity/volume/size/ply/material/gauge/length/
   diameter. Intake keys were "syringe_volume" (2 mL) and "type" ("3-ply surgical"), so the syringe
   capacity and the mask ply were never checked; the syringe primary became gauge and the mask primary
   material. Both lowest offers happen to be right, but a 5 mL syringe with a 23G needle would pass.
   The syringe title also shows "yes" from the known attribute with_needle.
3. **Implausible unit price passes** (syringe highest Rs 400/piece, really a box). No outlier check.
4. **MOQ missed** on the gloves lowest ("MOQ100000 Piece/Pieces" on the page), so a seller whose MOQ
   is ten times the requested quantity sets the lowest price.
5. Size lists: a requested "S" against "S, M, L" reads as mismatch because a bare "S" is not searched
   in titles (safe direction: drops, never includes).
6. Readers: www.justdial.com and store.independenceaustralia.com could not be read; mask stopped on the
   AI extraction budget.

## Run 3, 2026-10-26, after Task 20 (cost branch, join, check_sanity, R29, R30, MOQ prompt)

How it was run: commit f152ba0, `alembic upgrade head`, same server setup and `.env` (port 8016). The
five Run 2 researches were started again with `POST /api/research/{id}/start` (same questions and
answers). All five finished `done` in 31 to 64 s each, no failures. Lowest/highest from
`purchase_range` at qty 10000. Every lowest/highest URL was fetched again (httpx, browser UA,
`html_to_text`), the `price_quote` searched on the page, and the listing text around it read for
product type and variant. Every cited cost source URL was fetched and searched for rupee prices with
a per kg / per piece basis.

| Product | Offers (mfr / unconfirmed / excluded) | In range | Lowest | Highest | Right product/variant? |
|---|---|---|---|---|---|
| 2 mL syringe with needle | 8 (0 / 4 / 4) | 1 | Rs 3.45/piece, Thyrocare Technologies Ltd., Navi Mumbai, [TradeIndia](https://www.tradeindia.com/navi-mumbai/syringe-needles-city-208287.html) | same offer | Yes: "2ml 23G Syringe with Needle, medical-grade, sterilized for single use, Price: 3.45 INR/Piece, size 2ml". Seller type "Supplier, Exporter", so unconfirmed. Page says "MOQ 100 Piece/Pieces"; the offer has no MOQ (harmless at 10000) |
| 3-ply surgical mask | 7 (0 / 5 / 2) | 0 | none | none | No range. Shubh Dispo Care Rs 0.70 (MOQ 5000, the Run 2 lowest) came back `spec_unstated` this time. Shivay Surgical Rs 10 (the Run 2 "100% cotton" highest) and Thea-Tex Rs 15 were taken out by `unusually_high` (cost high Rs 1.02) |
| Nitrile examination gloves, M, powder-free | 11 (0 / 11 / 0) | 1 | Rs 6.60/piece (Price: 660/Box, box of 100), Akshyata Will Pharmaceuticals, Delhi, [ExportersIndia](https://www.exportersindia.com/indian-suppliers/nitrile-exam-gloves.htm) | same offer | Yes: "Nitrile Examination Surgical Glove, Medium size, box of 100, non-sterile". Flagged `unusually_low` only because the gloves cost card is wrong (issue 2). Page says "MOQ: 25 Box"; the offer has no MOQ (2500 gloves, harmless) |
| IV cannula 20G | 3 (1 / 1 / 1) | 1 | Rs 4.25/piece (lowest-MOQ fallback, MOQ 200000), Hi Tech Medicare Devices Pvt Ltd, Prayagraj, [ExportersIndia](https://www.exportersindia.com/hi-tech-medicare-devices/iv-cannula.htm) | same offer | Product yes (IV cannula with wings and injection port, PTFE/FEP). Variant partly: the listing title is "22G IV Cannula", "Gauge sizes available 14G to 26G", one price for all sizes. "Min. Order (MOQ) 200000 Pieces" was captured, so the card says all manufacturers need a larger order |
| Urine bag 2000 mL | 33 (11 / 21 / 1) | 8 | Rs 9.50/piece, Real Surgi Product, Jaipur, [ExportersIndia](https://www.exportersindia.com/jaipur/surgical-disposables.htm) | Rs 30.00/piece, Ribbel International Ltd., Kanpur, [ExportersIndia](https://www.exportersindia.com/kanpur/urine-bags.htm) | Both yes: "2000ml PVC Urine Collection Bag, Price: 9.50 - 10.50/Piece" and "PVC Urine Bags 2000ml, Price: 30 - 295/Piece, MOQ: 1000 Piece" (the 30 to 295 spread is wide; the low end is used). T-tap, tube length and sterility unstated (spec_partly_confirmed) |

Every lowest/highest `price_quote` was found on the refetched page.

### Cost cards

Lines are per finished unit. "Cited" means a verified web price; "estimate" means the planner's number,
shown with `estimated: true`. The overhead and scrap line (10%) is not counted below.

| Product | per_unit | low | high | Confidence | Cited / estimate lines |
|---|---|---|---|---|---|
| 2 mL syringe with needle | Rs 1.46 | Rs 1.32 | Rs 1.60 | low | 5 / 8 (needle and all 7 process steps are estimates) |
| 3-ply surgical mask | Rs 0.94 | Rs 0.83 | Rs 1.02 | medium | 5 / 4 (all materials cited, all process steps estimates) |
| Nitrile examination gloves | Rs 94.19 | Rs 93.57 | Rs 94.83 | low | 2 / 4. **Wrong**, see issue 2 |
| IV cannula 20G | Rs 2.70 | Rs 2.44 | Rs 2.93 | low | 3 / 5 (PTFE catheter and all process steps are estimates) |
| Urine bag 2000 mL | Rs 9.75 | Rs 8.76 | Rs 10.70 | low | 4 / 8 (hanger, label and all process steps are estimates) |

### Cost source links checked

The verified quote itself is not stored in the result (`Source` has url and title only), so each page
was checked for a rupee price with the right basis that is consistent with the line amount. Every
source page returned HTTP 200.

- Syringe: [ofbusiness polymers](https://www.ofbusiness.com/category/polymers-packaging) (PP,
  "₹85-100/kg" to "₹115-130/kg"; barrel, plunger, needle hub),
  [IndiaMART synthetic rubbers](https://dir.indiamart.com/impcat/synthetic-rubbers.html) (many "₹ N / kg";
  plunger seal), [IndiaMART blister paper](https://www.indiamart.com/proddetail/blister-packaging-paper-for-pharmaceutical-industry-2858650103812.html)
  ("₹135/kg"; individual pack). All consistent.
- Mask: [favouritehub non-woven price list](https://favouritehub.com/non-woven-fabric-price-list) ("₹85/kg";
  outer and inner layer), [TradeIndia meltblown](https://www.tradeindia.com/products/meltblown-non-woven-fabric-c6472521.html)
  ("Price: 300.00 INR/Kilograms"; filter layer), [TradeIndia nylon spandex](https://www.tradeindia.com/delhi/nylon-spandex-fabric-city-228067.html)
  ("Price: 300 INR/Kilograms"; earloop), [TradeIndia plastic coated wire](https://www.tradeindia.com/jaipur/plastic-coated-wire-city-197559.html)
  ("Price: 160 INR/Kilograms"; nose strip). All consistent.
- Gloves: [bhavikenterprise NBR](https://www.bhavikenterprise.in/nitrile-butadiene-rubber.html) ("₹175 / kg",
  "₹185 / kg"; glove body, consistent). [TradeIndia nitrile dipped gloves](https://www.tradeindia.com/bhiwandi/nitrile-dipped-gloves-city-183731.html)
  has "Price: 80 INR/Piece", but that is the selling price of a finished (industrial) dipped glove, not
  a dipping and curing rate. The number is on the page; the citation is wrong for the line.
- IV cannula: [steelhouseindia metal wires](https://www.steelhouseindia.co.in/metal-wires.html) ("₹170 /
  kilogram"; needle, consistent; the page also lists other wires at ₹2,500 and ₹40,000 / kg),
  [ofbusiness polymers](https://www.ofbusiness.com/category/polymers-packaging) (hub and cover, consistent).
- Urine bag: [dial4trade PVC film](https://www.dial4trade.com/suppliers/pharmaceutical-pvc-film.htm)
  ("₹103 / kg" to "₹157/kilogram"; bag body), [bazargpt PVC tube](https://bazargpt.com/product/medical-grade-pvc-tube-918673)
  ("₹130/kg"; tube), [ofbusiness ABS](https://www.ofbusiness.com/prices/polymers-packaging/abs) ("₹145-165/kg";
  T-tap), [ofbusiness polymers](https://www.ofbusiness.com/category/polymers-packaging) (connector). All consistent.

Every other cost line is labelled estimate.

### What Task 20 fixed

- Every item now has a cost card with cited material lines and labelled estimates.
- R29 works: implausible in-range prices against the cost are removed (mask Rs 10 cotton listing,
  urine bags Rs 45 and Rs 120).
- MOQ capture improved: "Min. Order (MOQ) 200000 Pieces" (cannula), "MOQ 100000" (Spark Lifesciences,
  urine bag) and "MOQ 5000" (Shubh Dispo) were captured.

### Issues still open (honest list; not tuned here)

1. **The cost branch starves the offer branch.** Budgets are shared (R22). All five runs now stop on
   the search and page budgets. One Tavily search per material and per process step plus two pages
   each takes up to about half of the 12 searches and 30 pages, mostly in the first step, before offer
   pages are read. In range went from 2/2/2/2/8 (Run 2) to 1/0/1/1/8. Options: a separate small cost
   budget, higher defaults, or fewer cost searches (for example materials only: process steps almost
   never have a citable per-piece rate, 0 of 25 process lines were validly cited).
2. **Gloves cost card is wrong.** The process search "glove dipping & curing rate India" returned a
   glove listing, and "Price: 80 INR/Piece" passed every check (on the page, number from the quote,
   per piece basis). The planner also mixed per-glove and per-box bases. Result: Rs 94 per glove,
   which flagged the right offer `unusually_low` (a warning only, it stays in range). A guard is
   needed, for example reject a cited line more than a few times the planner's estimate, or stop
   citing process steps.
3. **Cost quotes are not stored.** `Source` keeps url and title only, so a user (or this check) cannot
   see which number on the page was used. Add the verified quote to `Source`.
4. **`unusually_high` can empty a thin range** (mask: both in-range offers removed against a Rs 1.02
   cost high). Right for the cotton listing; not checked for Thea-Tex Rs 15.
5. Spec match is still unstable run to run: the Shubh Dispo Care Rs 0.70 mask was in range in Run 2
   and `spec_unstated` here.
6. MOQ still missed on two lowest listings ("MOQ 100 Piece/Pieces" syringe, "MOQ: 25 Box" gloves),
   both below the requested quantity, so the range is unaffected.
7. IV cannula: a one-price listing for "14G to 26G" with a 22G title is treated as a 20G match; it
   should probably be `ambiguous_variants`.
8. Readers: nihalhealthcare.com and www.justdial.com could not be read.

## Run 4, 2026-10-26, after Task 20 fix round 1 (R31 cost budget, R32 material-only search, R33 per-piece plan and cost-above-market guard, R34 cost quotes)

How it was run: commit 0d3ee36, same server setup and `.env` (port 8016), the same five researches
started again (same answers). All five finished `done` in 35 to 56 s each, no failures. Checks as in
Run 3. Cost quotes are now stored on each cited line, so every quote was searched on its refetched
source page.

| Product | Offers (mfr / unconfirmed / excluded) | In range (Run 3 -> 4) | Lowest | Highest | Right product/variant? |
|---|---|---|---|---|---|
| 2 mL syringe with needle | 22 (1 / 15 / 6) | 1 -> 7 | Rs 1.75/piece, Medmech Healthcare Pvt Ltd, [ExportersIndia](https://www.exportersindia.com/agra/syringes.htm) | same offer (the only in-range manufacturer, so the range uses it alone) | Yes: "2ml Disposable Syringe With Needle, Price: 1.75 - 2.50/Piece, size 2ml, needle stainless steel". 23G not stated (spec_partly_confirmed) |
| 3-ply surgical mask | 19 (2 / 16 / 1) | 0 -> 0 | none | none | No range. Eight masks between Rs 0.55 and Rs 5 were found but all are `spec_unstated` (the primary attribute became material, which listings rarely state; see Run 2 issue 2). Shivay Rs 10 and Thea-Tex Rs 15 again `unusually_high` |
| Nitrile examination gloves, M, powder-free | 25 (2 / 21 / 2) | 1 -> 2 | Rs 3.00/piece, Denplan, Angamali, [ExportersIndia](https://www.exportersindia.com/kochi/nitrile-exam-gloves.htm) | same offer (unconfirmed-only range) | Yes: "Nitrile Exam Gloves, powder free, Price: 3 - 6/Piece, sizes L, M, S". The page says "MOQ: 100 Box" (about 10000 gloves); the offer has no MOQ |
| IV cannula 20G | 5 (3 / 0 / 2) | 1 -> 1 | Rs 4.25/piece, Hi Tech Medicare Devices Pvt Ltd, [ExportersIndia](https://www.exportersindia.com/sirohi/iv-cannula.htm) | same offer | Yes, now the right variant: "20G IV Cannula with Wings and Injection Port, Price: 4.25 - 4.60/Piece", manufacturer |
| Urine bag 2000 mL | 22 (6 / 13 / 3) | 8 -> 5 | Rs 9.50/piece (MOQ 1000), Real Surgi Product, [ExportersIndia](https://www.exportersindia.com/imphal/medical-supplies.htm) | Rs 12.00/piece (MOQ 100), Advin Health Care, Ahmedabad, [TradeIndia](https://www.tradeindia.com/manufacturers/urine-collection-bag.html) | Both yes: "2000ml PVC Urine Collection Bag, Price: 9.50 - 10.50/Piece" and "Urine Collecting Bag, Medical PVC 2000ml, sterile ... Price Trend: 12.00 - 25.00 INR/Piece" (the TradeIndia text is labelled "Price Trend"). T-tap and tube length unstated |

Every lowest/highest `price_quote` was found on the refetched page.

### Cost cards

| Product | per_unit | low | high | Confidence | Cited / estimate lines | Quotes found on source page |
|---|---|---|---|---|---|---|
| 2 mL syringe with needle | Rs 1.60 | Rs 1.49 | Rs 1.71 | low (R33: above the lowest in-range offer, Rs 1.30) | 7 / 8 | 7 of 7 |
| 3-ply surgical mask | Rs 1.33 | Rs 1.21 | Rs 1.45 | medium | 6 / 5 | 5 of 6 (see issue 3) |
| Nitrile examination gloves | Rs 2.13 | Rs 1.99 | Rs 2.28 | medium | 3 / 8 | 3 of 3 |
| IV cannula 20G | Rs 3.80 | Rs 3.39 | Rs 4.20 | low | 2 / 10 | 2 of 2 |
| Urine bag 2000 mL | Rs 9.14 | Rs 8.10 | Rs 10.18 | medium | 6 / 7 | 6 of 6 |

All process lines are estimates (R32). The gloves card is now per glove (Rs 2.13 against a Rs 3 lowest
offer) and no longer flags the right offer.

### Cost quotes checked (quote, source)

- Syringe: "PP (Polypropylene) trades at ₹105-120 per kg currently." ([ofbusiness](https://www.ofbusiness.com/category/polymers-packaging); barrel, plunger, needle hub, needle cap), "₹284.50 per kg" ([bankbazaar rubber](https://www.bankbazaar.com/commodity-price/rubber-price.html); gasket, natural rubber price), "...stainless steel 304 pipes ... ₹195 to ₹250 per kg..." ([navrangsteel](https://www.navrangsteel.com/stainless-steel-304-price-per-kg); needle, pipe price used for needle tube), "₹ 180/Kilogram(s)" ([IndiaMART poly coated paper](https://www.indiamart.com/proddetail/medical-grade-poly-coated-paper-12442502897.html); packaging).
- Mask: "Starting ₹85/kg" ([favouritehub](https://favouritehub.com/non-woven-fabric-price-list); outer and inner layer), "Price: 300.00 INR / Kilograms" ([TradeIndia meltblown](https://www.tradeindia.com/products/meltblown-non-woven-fabric-c6472521.html)), "Price: 300 INR/Kilograms" ([TradeIndia elastic cords](https://www.tradeindia.com/ahmedabad/elastic-cords-city-178823.html); round mask elastic), "₹ 120/Kg" ([IndiaMART PVC coated GI wire](https://www.indiamart.com/proddetail/pvc-coated-chain-link-gi-wire-22130527848.html); nose wire). Packaging cited "If PP rate = ₹110/kg → Material cost = 0.138 kg × ₹110 = **₹15.18**" from dwarkeshpolyfab.com, which could not be refetched (connect error), so it is not confirmed; it is an example calculation in a blog, not a quoted price.
- Gloves: "Product Price: Rs 185 / Kg" ([bhavikenterprise NBR](https://www.bhavikenterprise.in/nitrile-butadiene-rubber.html)), "Approx. Price: Rs 29 / Kg" ([priyapapers duplex board](https://www.priyapapers.in/duplex-board-suppliers.html)), "₹ 45 Per Kilogram" ([dial4trade corrugated sheet](https://www.dial4trade.com/uma-corrupack-industries/corrugated-cardboard-sheet-pdid-10697728.htm)).
- IV cannula: PP quote as above (hub), "₹ 175 / Kg" ([IndiaMART synthetic rubbers](https://dir.indiamart.com/impcat/synthetic-rubbers.html); port cap). PTFE tube and needle are estimates (cost source budget reached).
- Urine bag: "₹ 110/Kg" ([IndiaMART medical PVC sheet](https://www.indiamart.com/proddetail/0-5mm-medical-grade-pvc-rigid-transparent-sheet-roll-24173978348.html); bag body), "PVC resin price today ₹85-100/kg." ([ofbusiness PVC](https://www.ofbusiness.com/prices/polymers-packaging/pvc); tube), PP quote as above (T-tap, hanger), "Price: 120 INR / Kilograms" ([TradeIndia PVC compound](https://www.tradeindia.com/products/pvc-film-compound-9892561.html); connector), "₹ 209 / Kg Get Latest Price" ([jagdambasales pouches](https://www.jagdambasales.in/plastic-packaging-pouch.html); packaging pouch).

### Budget notes

- Syringe: none (only "Could not read www.justdial.com").
- Mask: "Cost estimate: stopped early, source budget reached", "Stopped early: AI extraction budget reached" (offer branch, 30 calls).
- Gloves: none (only "Could not read www.facebook.com").
- IV cannula: "Cost estimate: stopped early, source budget reached".
- Urine bag: "Cost estimate: stopped early, source budget reached".

No offer run stopped on the search or page budget (Run 3: all five did).

### What the fix round changed

- R31: the offer branch no longer loses budget to the cost branch; in range went 1/0/1/1/8 (Run 3) to
  7/0/2/1/5. The cost branch now stops on its own page budget (8) on three products, leaving some
  materials as estimates.
- R32/R33: no process line is cited; the gloves cost card is per piece and plausible.
- R33 guard fired once (syringe: cost Rs 1.60 above the Rs 1.30 in-range offer), confidence low with note.
- R34: every cited line shows its quote.

### Issues still open (honest list; not tuned here)

1. **Mask has no range in Runs 3 and 4.** Cheap 3-ply masks are found (Rs 0.55 to Rs 1.80) but all are
   `spec_unstated` because the primary attribute is material (Run 2 issue 2: the intake key "type"
   carrying "3-ply surgical" is not used as the defining attribute). Not a cost-branch problem.
2. **Cost citations are price-of-something-similar, not always the exact grade**: PP and PVC resin
   prices for moulded parts are fine; natural rubber price for a synthetic gasket, SS 304 pipe price
   for needle tube, and a blog calculation for mask packaging are weak. Quotes are verbatim on the
   page, so the user can judge, but the line is labelled cited.
3. The mask packaging quote could not be refetched (connect error from this machine).
4. The cost page budget (8) runs out on products with many components (cannula, urine bag, mask);
   those materials fall back to estimates. Raising it to about 12 would cover typical BOMs.
5. The R33 guard compares with any in-range offer, including unconfirmed sellers (syringe: Rs 1.30 from
   unconfirmed sellers while the range itself uses the only manufacturer at Rs 1.75).
6. MOQ still missed on the gloves lowest ("MOQ: 100 Box"); TradeIndia "Price Trend" text is used as a price.

## Run 5, 2026-10-26, after Task 20 fix round 2 (strict per-kg quotes, R35 name kinds, R36 to R39)

How it was run: commit dc8fc88, same server setup and `.env` (port 8016), the same five researches
started again (same answers). Syringe, mask, gloves and cannula finished `done` in 43 to 50 s. **The
urine bag run hit OpenAI HTTP 429 (Too Many Requests)**: planning and every page extraction failed,
so it is not a valid result. It was started once more a minute later and hit 429 again (47 responses
with 429 in the server log), so no further runs were made. Checks as in Run 4: every lowest/highest
URL refetched and read; every cited cost quote searched on its refetched source page and read for
material.

| Product | Offers (mfr / unconfirmed / excluded) | In range (Run 4 -> 5) | Lowest | Highest | Right product/variant? |
|---|---|---|---|---|---|
| 2 mL syringe with needle | 19 (1 / 11 / 7) | 7 -> 7 | Rs 1.75/piece, Medmech Healthcare Pvt Ltd, [ExportersIndia](https://www.exportersindia.com/agra/syringes.htm) | same offer (only priced in-range manufacturer) | Yes: "2ml Disposable Syringe With Needle, Price: 1.75 - 2.50/Piece, size 2ml". Three unconfirmed sellers at Rs 105, 120 and 220 "per piece" (box prices, almost certainly) are flagged `unusually_high` but stay in range because the cost card is low confidence (R37); they are not in the displayed range only because a manufacturer exists |
| 3-ply surgical mask | 17 (5 / 11 / 1) | 0 -> 12 | Rs 0.50/piece, VS Prime Enterprise, Chennai, [ExportersIndia](https://www.exportersindia.com/chennai/earloop-masks.htm) | same offer (only priced in-range manufacturer) | Yes: "3 Ply Earloop Face Mask with Meltblown Layer, Price: 0.50/Piece, Number of Layers: 3 Ply, earloop". R35 works: ply is now primary. Flagged `unusually_low` (below 0.6 x cost low Rs 0.88) as a warning |
| Nitrile examination gloves, M, powder-free | 13 (1 / 11 / 1) | 2 -> 2 | Rs 5.00/piece, Dahanu Rubber Gloves Mfg. Co, Mumbai, [jyotgloves.com](https://www.jyotgloves.com/examination-gloves.html) | Rs 6.60/piece (660/Box of 100), Akshyata Will Pharmaceuticals, Delhi, [ExportersIndia](https://www.exportersindia.com/indian-suppliers/nitrile-exam-gloves.htm) | Lowest: product yes ("Nitrile Examination Gloves, Product Price: Rs 5/Piece, powder-free, non-sterile, pack size 100 pcs"), variant partly: "Size 7 inch", "Glove Grade Industrial". Highest: yes (Medium, box of 100, non-sterile) |
| IV cannula 20G | 16 (5 / 9 / 2) | 1 -> 4 | Rs 4.25/piece, Hi Tech Medicare Devices Pvt Ltd, Prayagraj, [ExportersIndia](https://www.exportersindia.com/indian-suppliers/iv-cannula.htm) | same offer | Yes: "20G IV Cannula with Wings and Injection Port, Price: 4.25 - 4.60/Piece, PTFE or FEP", manufacturer |
| Urine bag 2000 mL | invalid (OpenAI 429) | 5 -> n/a | n/a | n/a | Not evaluated. The retry found Salvavidas Rs 12 and Amkay Rs 30 (both right product, 2000 ml) from two extractions only; no cost card (planning failed) |

Every lowest/highest `price_quote` was found on the refetched page.

### Cost cards

| Product | per_unit | low | high | Confidence | Cited / estimate lines | Quotes on page, right material |
|---|---|---|---|---|---|---|
| 2 mL syringe with needle | Rs 1.25 | Rs 1.14 | Rs 1.38 | low | 5 / 8 | 5 of 5 |
| 3-ply surgical mask | Rs 0.96 | Rs 0.88 | Rs 1.05 | low (R33: above the Rs 0.50 lowest) | 3 / 8 | 3 of 3 |
| Nitrile examination gloves | Rs 6.23 | Rs 5.68 | Rs 6.78 | low (R33: above the Rs 5.00 lowest) | 3 / 6 | 3 of 3, but see issue 2 |
| IV cannula 20G | Rs 1.68 | Rs 1.58 | Rs 1.80 | low | 6 / 8 | 6 of 6 |
| Urine bag 2000 mL | none | | | | | (run invalid) |

### Cost quotes checked (quote, material, source)

- Syringe: "PP (Polypropylene) trades at ₹105-120 per kg currently." for barrel, plunger, hub ([ofbusiness](https://www.ofbusiness.com/category/polymers-packaging)), "₹ 175 / Kg" synthetic rubber elastomer for the gasket ([IndiaMART synthetic rubbers](https://dir.indiamart.com/impcat/synthetic-rubbers.html); the Run 4 natural-rubber citation is gone), "₹ 160 / Kg" medical grade (bactite) paper for the wrapper ([IndiaMART medical grade paper](https://dir.indiamart.com/impcat/medical-grade-paper.html)). Needle is an estimate.
- Mask: "Price: 300.00 INR / Kilograms" meltblown polypropylene for the filter layer ([TradeIndia](https://www.tradeindia.com/products/meltblown-non-woven-fabric-c6472521.html)), "545.00 INR / Kilograms" PVC coated galvanized iron wire for the nose wire ([TradeIndia](https://www.tradeindia.com/products/pvc-coated-galvanized-iron-wire-c5474892.html); the listing sits under wire mesh, a weak but same-material match), "Rs 150 / Kg" polypropylene pouches for packing ([saptthagiri](https://www.saptthagiri.com/polypropylene-pouches.html)). Outer and inner layers and earloops are now estimates (the favouritehub price list was rejected because "SMS" and "spunlace" sit next to its "Starting ₹85/kg").
- Gloves: "Product Price: Rs 185 / Kg" nitrile rubber NBR ([bhavikenterprise](https://www.bhavikenterprise.in/nitrile-butadiene-rubber.html)), "Price: 60 INR/Kilograms" duplex paper ([TradeIndia duplex paper](https://www.tradeindia.com/manufacturers/duplex-paper.html)), "~INR 45.31/kg in May" corrugated box index ([procurementresource](https://www.procurementresource.com/resource-center/corrugated-box-price-trends); a market report, not a seller price).
- IV cannula: "Rs 170 / Kilogram" SS 304 wire for the needle ([steelhouseindia](https://www.steelhouseindia.co.in/metal-wires.html)), PP quote as above for hub and luer cap, "₹ 50 / Kg" polyethylene for port and protector caps ([IndiaMART polyethylene](https://dir.indiamart.com/impcat/polyethylene.html)), "Price: 150 INR / Kilograms" PVC film sheet for the blister ([TradeIndia](https://www.tradeindia.com/products/pvc-film-sheet-c7632956.html)).

The Run 4 bad citations (blog calculation, natural rubber for a synthetic gasket, SS pipe for needle tube,
chain-link wire) did not recur.

### Budget notes

- Syringe: none ("Could not read nihalhealthcare.com").
- Mask: none ("Could not read www.justdial.com"); R33 note.
- Gloves: none; R33 note.
- IV cannula: none ("Could not read www.justdial.com", "www.globallinker.com").
- Urine bag: "Planning failed, using basic searches", many "Could not extract offers from ...", "Broader search failed, continuing" (all OpenAI 429).

No cost budget note on any valid run (R36 halves cost page use).

### Issues still open (honest list; not tuned here)

1. **Urine bag not evaluated** (OpenAI 429). R39 (TradeIndia "Price Trend") is covered by a unit test only.
2. **Gloves cost card is still too high** (Rs 6.23 per glove): the planner costed a whole 100-glove box
   (Rs 2.28) as one glove's packaging despite the per-piece instruction. R33 caught it (low confidence,
   note). A deterministic guard (for example packaging mass per piece) is not in place.
3. **R37 keeps box prices in range when the cost is low confidence**, and most cost cards are low
   confidence (any estimated material line makes them low). Syringe: Rs 105, 120 and 220 "per piece"
   sellers stay in range with only a warning; they would form the highest if no manufacturer existed.
4. Mask: outer/inner layer prices are now estimates because the deny map rejects a nonwoven price list
   that mentions several grades; strict but loses a real price.
5. Gloves lowest is an industrial-grade, 7 inch listing titled "Nitrile Examination Gloves".
6. A market index ("~INR 45.31/kg in May") passes as a cited price; it is a real per-kg number for the
   right material but not a seller offer.

## Split live check, 2026-10-26, after Task 21 (part research and split API)

Not run. Both attempts (about 45 seconds apart) failed at the first step: `POST /api/research` for
"2 mL disposable syringe with needle, 10000 units" returned HTTP 429 `llm_quota` ("OpenAI rate limit or
quota exceeded"), so no research could be created and no split was started. No per-part cheapest offers
were recorded and no IV set was tried. The split path is covered by unit and API tests with fakes only
(`backend/tests/test_split.py`); its behaviour against live listings is unverified.

## Run 6 (final), 2026-10-27, Task 31

**Not run: OpenAI blocked.** Before any research, one cheap call (`responses.create`, model `gpt-4.1`,
"Reply with OK", 16 output tokens) returned HTTP 429 `insufficient_quota` / `credit_balance_exhausted`
("You have no credits remaining"). One retry 60 s later returned the same. This is an exhausted
balance, not a transient rate limit, so no further attempts were made.

Not evaluated in this run, so still open:

- The five eval products after fix rounds R35 to R40 (Run 5 is the latest valid result for syringe,
  mask, gloves and cannula).
- Urine bag 2000 mL: last valid result is Run 4 (Run 5 was invalid, 429).
- The pasted multi-line requirement (2 products), the medicine text ("Medicines are out of scope"),
  the multi-item, blurry and medicine photos: covered by tests with fakes only
  (see [corner-cases.md](corner-cases.md)).
- Split and research for the syringe and an IV set: never run live (see the split live check above).

To finish this evaluation: add OpenAI credits (and rotate the keys, see README), then repeat Run 5's
procedure for all five products with the same answers, plus the four extra inputs above and the split
check, and append the results here.

### Screenshots (2026-10-27)

Taken with headless Chrome at 1600 x 1000 against the existing `backend/data/app.db` (API on 8016,
Vite on 5174, because a server was already on 8015). Compared with
`docs/superpowers/specs/mockups/app-v3.html`.

| File | Page | Matches the mockup? |
|---|---|---|
| [new-research.png](screenshots/new-research.png) | New research (Input step) | Yes: chocolate brown primary button and brand mark, cream background with warm gradient, glass sidebar, content centred in the ~820 px column, step bar top right |
| [details.png](screenshots/details.png) | Details step of a draft syringe research | Yes: centred column, generated questions with segmented and number controls, inline required errors, Start research disabled until answered |
| [results.png](screenshots/results.png) | Results for the Run 5 syringe | Mostly: two cards side by side in the wide container like the mockup; shows only a Lowest tile because lowest and highest are the same listing; header reads "12 manufacturers" for a one-listing range (corner-cases Known gap 4); split strip is below the fold |
| [manufacturers.png](screenshots/manufacturers.png) | Manufacturers directory | Yes in style (glass table, star column, brown accents); the table uses the wide container. Shows duplicate rows for one company with different city text (Known gap 5) |
| [settings.png](screenshots/settings.png) | Settings | Yes: centred glass card, configured badges, budgets, blocked sites; budget labels are plain key names ("llm calls") |
