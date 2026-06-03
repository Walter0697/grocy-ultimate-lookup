# Roadmap

## Phase 1: Stabilize Current Core

- [v] Create standalone FastAPI lookup service.
- [v] Add Open Food Facts adapter.
- [v] Add Open Products Facts adapter.
- [v] Add Open Beauty Facts adapter.
- [v] Add Open Pet Food Facts adapter.
- [v] Add UPCItemDB adapter.
- [v] Add SQLite cache for successful lookup results.
- [v] Add source toggles for Open Facts and UPCItemDB.
- [v] Add orchestrator tests for ranking, cache hits, and not-found behavior.
- [v] Add normalization layer for product names, brand, size, count, and variant.
- [v] Preserve raw source output alongside normalized output.
- [v] Add real barcode fixture tests using the six sample barcodes.
- [v] Decide whether Grocy receives raw source names or normalized names.

## Phase 2: Better Grocy Integration

- [v] Add thin Grocy barcode lookup plugin wrapper.
- [v] Install plugin into Grocy's persistent plugin folder.
- [v] Configure Grocy to use `UltimateBarcodeLookupPlugin`.
- [v] Verify Grocy can resolve an Open Food Facts hit through the custom plugin.
- [v] Verify Grocy can resolve a UPCItemDB fallback hit through the custom plugin.
- [v] Verify Grocy returns `null` for not-found lookups.
- [ ] Improve Grocy plugin installation docs.
- [ ] Add plugin troubleshooting docs for host networking and service health.
- [ ] Decide where lookup metadata should live in Grocy.
- [ ] Add optional source marker handling.
- [ ] Confirm Grocy UI behavior for manual edits after auto-fill.

## Phase 3: Local Knowledge Base

- [ ] Add local confirmed-match table.
- [ ] Prefer confirmed local matches before external sources.
- [ ] Add manual override endpoint.
- [ ] Store user-confirmed product name separately from source result.
- [ ] Add correction flow for previously confirmed barcode mappings.
- [ ] Add tests for local confirmed-match priority.

## Phase 4: Web Search Fallback

- [ ] Add web search provider abstraction.
- [ ] Search exact barcode when database sources miss.
- [ ] Filter candidate URLs for likely product pages.
- [ ] Extract `schema.org` JSON-LD product data when available.
- [ ] Extract Open Graph product metadata when available.
- [ ] Extract embedded product JSON when available.
- [ ] Return low-confidence web candidates without auto-trusting them.
- [ ] Add tests with saved page fixtures.

## Phase 5: LLM Extraction Fallback

- [ ] Add LLM provider abstraction.
- [ ] Feed limited page content to LLM only after structured extraction fails.
- [ ] Require JSON output matching the normalized product schema.
- [ ] Mark LLM results as `llm_fallback`.
- [ ] Add stricter confidence handling for LLM-derived results.
- [ ] Prevent LLM fallback from overwriting confirmed local cache.
- [ ] Add tests for malformed or low-confidence LLM output.

## Phase 6: Optional External App

- [ ] Add external barcode scan API endpoint.
- [ ] Add simple lookup UI.
- [ ] Add optional Grocy API writeback after confirmation.
- [ ] Add Telegram confirmation flow.
- [ ] Support scanner workflows outside the Grocy UI.
- [ ] Reuse the same lookup core for Grocy plugin and external app paths.
