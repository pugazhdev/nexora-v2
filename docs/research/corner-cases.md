# Corner cases (spec section 10)

One row per row of section 10 of
[the design spec](../superpowers/specs/2026-10-26-factory-price-research-design.md). Each row names the
test that covers it or a dated manual check with what was observed. Backend tests are
`backend/tests/<file>::<test>`, frontend tests are `frontend/src/<path>::"<test name>"`. Every name below
was checked to exist with grep on 2026-10-27.

Rows marked **gap** behave differently from the spec today; they are listed again under
[Known gaps](#known-gaps). Gaps 1 to 4 were fixed in the final fix wave (2026-10-27); their rows name the new tests.

Live checks were not possible on 2026-10-27: the OpenAI key returned HTTP 429 `insufficient_quota`
("You have no credits remaining") on a one-token call and again 60 s later. Rows that needed a live
photo (blurry, medicine, image and text disagree) are covered by tests with fakes only.

## Input

| Case | Covered by | Notes |
|---|---|---|
| No image and no text | `test_api_intake.py::test_analyse_without_input_400`, `test_intake_graph.py::test_empty_input_rejected`, `features/research/InputStep.test.tsx::"disables Analyse until there is input"` | |
| Corrupt, unsupported, or oversized image | `test_image_validation.py::test_truncated_image_rejected`, `::test_oversize_rejected`, `::test_gif_not_permitted`, `::test_text_file_with_image_extension_rejected_by_content`, `::test_pixel_limit_enforced`, `test_api_intake.py::test_bad_image_not_saved`, `features/research/InputStep.test.tsx::"rejects unsupported files inline"` | |
| Image and text disagree | `test_intake_graph.py::test_text_wins_and_injected_text_is_delimited_data` (added in this pass), `test_intake_graph.py::test_image_and_text_passes_both` | The rule lives in the intake prompt (`app/intake/prompts.py`); the test pins the rule text and that both inputs reach the model. Whether the model obeys it was not checked live (429) |
| Blurry / dark / no product | `test_screen.py::test_blurry_with_no_items_message`, `features/research/InputStep.test.tsx::"shows the message and stays when nothing is in scope"` | Messages for blurry, too dark, and a generic "No hospital consumable found" |
| Photo of a medicine | `test_screen.py::test_medicine_kept_unticked_with_reason`, `test_api_intake.py::test_cannot_select_out_of_scope_item`, `features/research/SelectStep.test.tsx::"disables out-of-scope rows and shows the reason"` | "Medicines are out of scope" |
| Photo of capital equipment | `test_screen.py::test_medicine_kept_unticked_with_reason` (same test asserts the equipment row) | "Equipment, not a consumable" |
| More than 10 items | `test_screen.py::test_cap_at_max_items_with_note` | "Showing the first 10 items" |
| Same item twice | `test_screen.py::test_duplicates_merged` | Same normalised name and known attributes |
| Quantities in Indian formats | `test_quantity.py::test_parse_quantity`, `test_screen.py::test_quantity_prefilled_from_hint`, `test_screen.py::test_quantity_default_normalised_by_unit`, `lib/format.test.ts::"parses grouped and plain numbers"` | 1,00,000, 1 lakh, 10 boxes of 100 |
| Boxes with unknown box size | `test_screen.py::test_boxes_without_size_adds_basis_question`, `test_screen.py::test_boxes_hint_default_none_with_basis_question`, `test_runs.py::test_quantity_multiplies_unit_basis` | Adds "Pieces per box" |
| Text is not a requirement | `test_screen.py::test_blurry_with_no_items_message` (asserts the not-found message for `no_product`, `ok`, `partial` and for a `not_medical`-only result), `test_screen.py::test_not_medical_dropped` | |
| Prompt injection in pasted text or image text | `test_intake_graph.py::test_text_wins_and_injected_text_is_delimited_data` (added), `test_intake_schemas.py::test_strict_schema_ok` | Input sits inside `<user_input>`; output is the strict schema only |

## Questions and confirmation

| Case | Covered by | Notes |
|---|---|---|
| Item needs no questions | `test_screen.py::test_quantity_question_always_present`, `features/research/DetailsStep.test.tsx::"shows only selected in-scope items, summary line, and Looks complete for quantity only"` | |
| Required answer missing | `test_intake_schemas.py::test_validate_required_missing`, `test_runs.py::test_start_rejects_missing_answers`, `features/research/DetailsStep.test.tsx::"shows server answer errors and disables Start; enabled when clean"`, `::"maps 400 details.items onto fields"` | |
| Number out of range, non-numeric | `test_intake_schemas.py::test_validate_number_range`, `::test_validate_number_rejects_non_finite`, `features/research/QuestionField.test.tsx::"number: Indian grouping, unit suffix, number value, empty is null, junk ignored"` | Server re-validates on PATCH and on start |
| User deselects every item | `features/research/SelectStep.test.tsx::"disables Continue when nothing is ticked"`, `test_runs.py::test_start_rejects_when_every_item_deselected` (added) | Details also disables Start when no item is selected (`n === 0` in `DetailsStep.tsx`) |
| User edits answers after a finished run | `test_api_runs.py::test_edit_answers_after_done_then_start_creates_new_run`, `test_repo.py::test_new_run_keeps_old_result`, `test_api_intake.py::test_patch_after_done_run_leaves_run_untouched`, `features/results/ResultsStep.test.tsx::"select loads an earlier run read-only; Back to latest returns"` | |

## Research

| Case | Covered by | Notes |
|---|---|---|
| OpenAI key missing or invalid | `test_api_intake.py::test_analyse_without_key_503`, `test_split.py::test_start_and_split_503_when_llm_not_configured`, `test_llm.py::test_401_maps_to_auth_error`, `features/research/InputStep.test.tsx::"shows the server error message"` | Message: "Set OPENAI_API_KEY, OPENAI_MODEL and OPENAI_VISION_MODEL in backend/.env" |
| Tavily key missing | `test_research_graph.py::test_tavily_not_configured_runs_on_web_search_only`, `test_research_graph.py::test_tavily_not_configured_writes_estimate_note` | Research runs on OpenAI web search only; the plan step writes the note "Search is using OpenAI web search only; material costs are estimates." (gap 1, fixed) |
| Both search sources fail | `test_research_graph.py::test_both_search_sources_down_fails_with_provider_message`, `test_research_graph.py::test_one_source_down_still_completes` | When every attempted search call failed and no offer was built, the item fails with the provider's message and shows Retry (gap 2, fixed) |
| Rate limit / quota | `test_llm.py::test_429_maps_to_quota_error`, `test_tavily.py::test_429_and_5xx_are_temporary`, `test_nodes_offers.py::test_tavily_transient_failure_retried_once_charging_budget_once`, `::test_tavily_fails_twice_gives_note`; manual 2026-10-26 and 2026-10-27 (see notes) | Analyse returns HTTP 429 `llm_quota` "OpenAI rate limit or quota exceeded" (observed live 2026-10-26, eval-log split check). During research a quota or key error (`LLMQuotaError`, `LLMAuthError`) is recorded; when no offer was built the item fails with the provider's message and shows Retry: `test_research_graph.py::test_llm_quota_mid_research_fails_with_quota_message`, `::test_llm_auth_error_with_offers_still_finishes` (gap 3, fixed). A 429 is still not retried inside the run |
| Zero candidates | `test_research_graph.py::test_no_offers_broadens_then_returns_empty_with_queries`, `test_nodes_offers.py::test_route_after_offers_broadens_once`, `features/results/PurchaseCard.test.tsx::"empty state with queries"` | |
| No confirmed manufacturer, some unconfirmed | `test_tiers.py::test_calculator_cases[no confirmed manufacturer uses unconfirmed only]`, `features/results/PurchaseCard.test.tsx::"unconfirmed label"` | |
| Only traders / retailers | `test_nodes_offers.py::test_build_offers_excludes_trader`, `test_tiers.py::test_calculator_cases[only excluded offers gives all nulls]`, `features/results/PurchaseCard.test.tsx::"all manufacturers list: tags, min N, hides excluded"`, `::"empty state with queries"` | |
| Only price-on-request listings | `test_nodes_offers.py::test_build_offers_gst_tiers_and_price_on_request`, `test_tiers.py::test_calculator_cases[in_range false is ignored]`, `features/results/PurchaseCard.test.tsx::"lists price-on-request makers with links when no offer is priced (I3)"` | Listed with the "Price on request" tag and a link, also when no price forms a range |
| Pack price with unknown pack size | `test_prices.py::test_box_price_without_count_is_flagged`, `test_nodes_offers.py::test_build_offers_flags_box_price_without_count` | "Price basis unclear", not in range |
| Several variants at one price | `test_spec.py::test_ambiguous_when_title_lists_several_capacities`, `test_spec.py::test_mismatch_beats_ambiguous` | |
| Non-INR price | `test_prices.py::test_foreign_currency_after_number_is_other`, `test_nodes_offers.py::test_build_offers_drops_non_inr_price` (added) | Dropped |
| Page blocks bots | `test_pages.py::test_403_falls_back_to_tavily_extract`, `::test_robots_block_and_503_fall_back`, `::test_captcha_falls_back`, `::test_both_fail_returns_none`, `test_nodes_offers.py::test_fetch_extract_unreadable_page_is_note` | "Could not read host" note |
| Same manufacturer on several platforms | `test_sellers.py::test_merge_keeps_cheapest_and_links_others`, `test_nodes_offers.py::test_same_listing_on_two_directory_pages_is_one_offer` | |
| One very low outlier | `test_sanity.py::test_unusually_low_flag`, `test_sanity.py::test_floor_skips_unusually_low_offer` | |
| One very high outlier | `test_sanity.py::test_high_outlier_removed_from_range`, `::test_no_floor_cut_without_cost`, `::test_one_mis_scaled_cheap_price_does_not_remove_genuine_offers_without_cost`, `::test_pack_prices_cut_by_cost_whatever_its_confidence` | Rules R29, R37, R40; the 30x floor cut needs a cost estimate |
| Single usable offer | `test_tiers.py::test_calculator_cases[single offer gives same lowest and highest]`, `features/results/PurchaseCard.test.tsx::"single offer"`, `::"manufacturer count is the range pool only (G4)"` | The count is the range pool (gap 4, fixed) |
| Quantity below all MOQs | `test_tiers.py::test_calculator_cases[quantity below every MOQ falls back to lowest-MOQ tiers]`, `features/results/PurchaseCard.test.tsx::"fallback note when every maker needs a larger order"` | |
| Material prices not found | `test_research_graph.py::test_material_price_without_quote_is_estimate`, `test_cost.py::test_uncited_line_marked_estimated`, `test_cost.py::test_confidence_levels` | "estimate, no source" tag |
| Budget exhausted mid-run | `test_research_graph.py::test_budget_exhausted_finishes_with_note`, `test_research_graph.py::test_cost_branch_budget_leaves_offer_budget_untouched` | |
| Wall-clock timeout | `test_budget.py::test_expired_uses_clock`, `test_nodes_offers.py::test_route_after_offers_stops_when_expired`, `test_runs.py::test_timeout_marks_failed` | The in-graph clock finishes with what was found ("Stopped early: time limit reached"); a hard limit of item timeout plus a grace period fails the item as a safety net |
| User cancels | `test_runs.py::test_cancel_marks_running_and_queued_cancelled`, `::test_cancel_discards_result_returned_after_cancel`, `test_research_graph.py::test_cancel_raises_cancelled`, `test_api_runs.py::test_cancel_endpoint` | |
| Server restart during research | `test_api_runs.py::test_restart_marks_interrupted_and_retry_works`, `test_runs.py::test_shutdown_marks_running_and_queued_interrupted`, `features/research/ResearchStep.test.tsx::"interrupted item shows message and Retry posts"` | |
| User closes the browser | `test_runs.py::test_items_run_one_after_another` (runs complete with no client attached), `components/shell/Sidebar.test.tsx::"shows counts and a pulsing dot only for researching items"` | Runs are asyncio tasks owned by `RunService`, not by the request |
| Two research runs at once | `test_runs.py::test_concurrency_limited_across_research` | `RESEARCH_CONCURRENCY` (default 2) |
| Scraped page tries prompt injection | `test_nodes_offers.py::test_build_offers_prompt_injection_page`, `test_nodes_offers.py::test_build_offers_drops_hallucinated_price` | Data block plus quote verification |

## Split research

| Case | Covered by | Notes |
|---|---|---|
| Product not splittable | `test_split.py::test_split_not_splittable_409`, `features/results/SplitStrip.test.tsx::"hidden when not splittable or no parts"` | |
| A part finds no manufacturer | `test_split.py::test_missing_part_marks_incomplete`, `features/results/SplitStrip.test.tsx::"incomplete"` | |
| Split pressed twice | `test_split.py::test_split_twice_while_running_409`, `features/results/SplitStrip.test.tsx::"running state"`, `::"done shows table and parts total"` (asserts the "Research again" button) | |

## Known gaps

1. Fixed: Tavily key missing now writes the note "Search is using OpenAI web search only; material costs are estimates." (`test_research_graph.py::test_tavily_not_configured_writes_estimate_note`).
2. Fixed: both search sources failing with no offer built fails the item with the provider's message, so it shows Retry (`test_research_graph.py::test_both_search_sources_down_fails_with_provider_message`).
3. Fixed: an OpenAI quota or key error during research fails the item with the provider's message when no offer was built (`test_research_graph.py::test_llm_quota_mid_research_fails_with_quota_message`). It is still not retried, and a run that built some offers finishes `done` with notes.
4. Fixed: the purchase card header "N manufacturers" counts only the range pool (`features/results/PurchaseCard.test.tsx::"manufacturer count is the range pool only (G4)"`).
5. The Manufacturers directory shows one company several times when its city is written differently on different pages ("Prayagraj", "Naini, Prayagraj", "Sant Ravidas Nagar"), because the merge key is name plus city.
