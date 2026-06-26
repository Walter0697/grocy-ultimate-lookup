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
- [v] Improve Grocy plugin installation docs.
- [v] Add plugin troubleshooting docs for host networking and service health.
- [v] Decide where lookup metadata should live in Grocy.
- [v] Add optional source marker handling.
- [v] Confirm Grocy UI behavior for manual edits after auto-fill.

## Phase 3: Local Knowledge Base

- [v] Add local confirmed-match table.
- [v] Prefer confirmed local matches before external sources.
- [v] Add manual override endpoint.
- [v] Store user-confirmed product name separately from source result.
- [v] Add correction flow for previously confirmed barcode mappings.
- [v] Add tests for local confirmed-match priority.

## Phase 4: Web Search Fallback

- [v] Add web search provider abstraction.
- [v] Search exact barcode when database sources miss.
- [v] Filter candidate URLs for likely product pages.
- [v] Extract `schema.org` JSON-LD product data when available.
- [v] Extract Open Graph product metadata when available.
- [v] Extract embedded product JSON when available.
- [v] Return low-confidence web results without caching them as trusted results.
- [v] Add tests with saved page fixtures.

## Phase 4.5: Web Match Hardening

- [v] Detect exact barcode matches in structured product fields.
- [v] Detect barcode evidence in page content.
- [v] Reject structured products with conflicting barcode fields.
- [v] Detect search-title and product-name mismatches.
- [v] Add explainable `match_reason` and `match_warnings` fields.
- [v] Calculate dynamic confidence from barcode evidence and mismatch warnings.
- [v] Keep hardened web results editable through Grocy autofill.
- [v] Add tests for exact matches, conflicts, and suspicious mismatches.

## Phase 5: LLM Extraction Fallback

- [v] Add LLM provider abstraction.
- [v] Feed limited page content to LLM only after structured extraction fails.
- [v] Require JSON output matching the normalized product schema.
- [v] Mark LLM results as `llm_fallback`.
- [v] Add stricter confidence handling for LLM-derived results.
- [v] Prevent LLM fallback from overwriting confirmed local cache.
- [v] Add tests for malformed or low-confidence LLM output.

## Phase 5.5: Coding-Agent Research Fallback

- [v] Add persisted coding-agent barcode research jobs.
- [v] Mount Codex authentication read-only using the Pochita pattern.
- [v] Run one isolated ephemeral Codex session per difficult barcode.
- [v] Deduplicate active agent searches by barcode.
- [v] Keep Grocy requests fast while agent research runs in the background.
- [v] Add agent search status, retry, and delete endpoints.
- [v] Prefer stronger database results over researched agent results.
- [v] Add tests for agent job persistence and lookup priority.

## Phase 5.6: Multilingual Product Names

- [v] Detect language-specific names from Open Facts sources.
- [v] Prefer sourced English names over explicitly non-English names.
- [v] Preserve original-language names as lookup metadata.
- [v] Persist trusted non-English fallback context with agent jobs.
- [v] Translate the trusted original only after sourced English research fails.
- [v] Rank sourced English above translated English and translated English above non-English.
- [v] Expose agent research status in lookup responses.
- [v] Add lookup provenance and original names to Grocy descriptions.
- [v] Add tests for multilingual ranking and fallback behavior.

## Phase 6: Optional External App

- [v] Add external barcode scan API endpoint.
- [v] Check Grocy for existing barcodes before external lookup.
- [v] Add idempotent scan event log with add, remove, and set modes.
- [v] Add responsive image-card dashboard.
- [v] Replace separate dashboard sections with a unified Gallery Wall event grid.
- [v] Add compact manual scanner with mode, quantity, and location selection.
- [v] Replace the manual scanner form with barcode-first preview and confirmation popup.
- [v] Add Grocy-first, non-mutating scan preview endpoint.
- [v] Automatically create complete trusted lookup matches in Grocy.
- [v] Show loading states during barcode lookup and Grocy writes.
- [v] Forward optional scan location to Grocy stock operations.
- [v] Make only uncertain, unknown, researching, and failed cards require review.
- [v] Add pending unknown-product review queue.
- [v] Add Grocy product creation and stock writeback after confirmation.
- [v] Preserve and apply the original pending stock operation after confirmation.
- [v] Add scanner device authentication.
- [v] Add device heartbeat and online/offline status.
- [v] Add device-friendly scanner endpoint with server-generated event IDs.
- [v] Build Raspberry Pi scanner client prototype.
- [v] Add keyboard scanner simulator for mode, quantity, and location controls.
- [v] Add state-file scanner runtime/control split.
- [ ] Evaluate ESP32 scanner client.
- [v] Support scanner workflows outside the Grocy UI.
- [v] Reuse the same lookup core for Grocy plugin and external app paths.

## Phase 7: Release Hygiene and Operational Visibility

- [ ] Define semantic versioning policy for the lookup service.
- [v] Store the app version in one source of truth.
- [ ] Add `GET /version` with version, git commit, build time, and image tag when available.
- [ ] Show version and short commit in the dashboard UI.
- [ ] Show version and short commit in the settings UI.
- [v] Include scanner client version in heartbeat payloads and device status.
- [v] Tag Docker images with semantic versions in CI/CD.
- [ ] Document release and tagging flow.

## Phase 8: Community Catalog Federation

- [v] Export manually confirmed products to GitHub catalog repositories.
- [v] Initialize catalog repositories with a README on first product push.
- [v] Support auto-push and manual pending-review push flows.
- [v] Store pending manual catalog products in SQLite for review mode.
- [v] Include uploaded and external product images in catalog folders when enabled.
- [v] Read community catalog source repositories as lookup providers.
- [v] Use the saved GitHub PAT for private catalog source reads.
- [v] Let users add, remove, enable, disable, and reorder community catalog sources.
- [v] Serve catalog sibling images through the lookup service instead of returning internal source URLs.
- [v] Document why community catalogs complement, rather than compete with, Open Facts databases.
- [v] Add catalog validation command or endpoint.
- [v] Add catalog source health/status checks.
- [ ] Add conflict UI when multiple catalogs return different products for the same barcode.
- [ ] Add optional public/community catalog index.
- [v] Add catalog metadata for region, store, language, and category scope.

## Phase 9: Configurable Lookup Strategy

- [v] Add SQLite-backed lookup settings.
- [v] Add settings page sections for credentials, export, catalog sources, and lookup methods.
- [v] Reorder lookup providers with animated drag-and-drop.
- [v] Include Grocy current data, Ultimate Lookup cache, community catalogs, Open Facts, UPCItemDB, web search, LLM fallback, and Codex fallback in the provider list.
- [v] Disable and lock unavailable LLM and Codex provider rows.
- [v] Configure LLM base URL, API key, and model from the settings UI.
- [v] Configure GitHub catalog credentials from the settings UI.
- [ ] Add import/export for settings backup.
- [ ] Add reset-to-defaults for provider order.
- [ ] Add per-provider status and last-error visibility.

## Phase 10: Open Database Contribution Bridge

- [ ] Add optional catalog fields that map cleanly to Open Facts schemas, such as category, country, language, labels, ingredients, and packaging.
- [ ] Detect catalog records that are eligible for Open Food Facts, Open Products Facts, Open Beauty Facts, or Open Pet Food Facts contribution.
- [ ] Add an upstream contribution preview UI with missing-field warnings.
- [ ] Map catalog `product.json` records into target open database payloads.
- [ ] Require user approval before any upstream contribution.
- [ ] Store upstream contribution status and target database links in catalog metadata.
- [ ] Add guardrails to avoid blindly pushing partial or context-specific records into public databases.
