# grocy-ultimate-lookup

Multi-source barcode lookup service for Grocy.

The main app is a FastAPI service. Grocy integration is kept as a thin PHP
plugin wrapper in `plugin/grocy/` so the lookup logic stays outside Grocy.

## Current Sources

- Open Food Facts
- Open Products Facts
- Open Beauty Facts
- Open Pet Food Facts
- UPCItemDB trial endpoint
- Web search fallback with structured page extraction

## Run

```bash
cp .env.example .env
docker compose up -d
```

Service:

```text
http://localhost:9290/lookup/057000013165
```

## Response Shape

```json
{
  "barcode": "057000013165",
  "found": true,
  "result": {
    "barcode": "057000013165",
    "name": "Heinz Tomato Ketchup",
    "raw_name": "Heinz Tomato Ketchup",
    "normalized_name": "Heinz Tomato Ketchup",
    "brand": "Heinz",
    "quantity": null,
    "size": null,
    "count": null,
    "variant": null,
    "image_url": null,
    "source": "open_food_facts",
    "confidence": 0.95,
    "raw_url": "https://world.openfoodfacts.org/api/v0/product/057000013165.json",
    "raw_payload": {}
  },
  "candidates": []
}
```

## Grocy Plugin

The Grocy plugin folder is intentionally small. It should only call this
service and translate the response into Grocy's expected barcode lookup format.

See `plugin/grocy/README.md`.

Default Grocy behavior:

- Product names use `normalized_name`.
- Source markers are not appended to product names.
- Lookup metadata stays in the lookup service and internal debug fields.
- Grocy's UI can still edit auto-filled fields before saving.

## Local Confirmed Products

Local confirmed products are user-corrected barcode mappings. They are stored
separately from external lookup cache and always win over cached or external
source results.

Create or correct a confirmed product:

```bash
curl -sS -X PUT 'http://localhost:9290/local-products/810669032478' \
  -H 'Content-Type: application/json' \
  -d '{"name":"My Confirmed Product","brand":"My Brand","quantity":"1 box"}'
```

Fetch a confirmed product:

```bash
curl -sS 'http://localhost:9290/local-products/810669032478'
```

Delete a confirmed product:

```bash
curl -sS -X DELETE 'http://localhost:9290/local-products/810669032478'
```

After a confirmed product is saved, normal lookup returns it:

```bash
curl -sS 'http://localhost:9290/lookup/810669032478'
```

The returned lookup result uses:

```text
source=local_confirmed
confidence=1.0
```

## Web Search Fallback

Web search runs after local confirmed products, cache, Open Facts, and
UPCItemDB miss. It searches the exact barcode and tries to extract product data
from candidate product pages using:

- `schema.org` JSON-LD product data
- embedded page JSON
- Open Graph product metadata

Web-derived results use evidence-based low confidence but can still be returned
as the best lookup result. This lets Grocy prefill the editable product form. If
the web result is wrong, edit it before saving in Grocy.

Low-confidence web results are not cached by default. That keeps them as
best-effort suggestions until you either save the product in Grocy or confirm it
through the local confirmed-products API.

Example response shape for a web-only match:

```json
{
  "barcode": "067489302124",
  "found": true,
  "result": {
    "barcode": "067489302124",
    "name": "Possible Retailer Product",
    "source": "web_json_ld",
    "confidence": 0.65,
    "match_reason": "barcode_in_structured_data",
    "match_warnings": [],
    "raw_url": "https://retailer.example/product"
  },
  "candidates": []
}
```

Important settings:

```text
CACHE_MIN_CONFIDENCE=0.7
ENABLE_WEB_SEARCH=true
WEB_SEARCH_MAX_RESULTS=5
WEB_SEARCH_FETCH_LIMIT=3
```

Raise or lower `CACHE_MIN_CONFIDENCE` to control which lookup results are cached.
Keep it above web fallback confidence if web results should remain fresh
best-effort suggestions.

### Web Match Confidence

Web confidence is explainable and based on barcode evidence:

| Evidence | Confidence |
|---|---:|
| Exact barcode in structured product fields | `0.65` |
| Exact barcode elsewhere in page content | `0.55` |
| Search result only | `0.45` |
| Search title conflicts with extracted product name | capped at `0.40` |

Recognized structured barcode fields include `barcode`, `ean`, `gtin`,
`gtin12`, `gtin13`, `gtin14`, `sku`, and `upc`.

If a structured product explicitly contains a different barcode, that product
candidate is rejected. Search-title conflicts are kept as editable Grocy
suggestions but include:

```json
{
  "match_reason": "barcode_in_structured_data",
  "match_warnings": ["search_title_product_name_mismatch"]
}
```

## LLM Extraction Fallback

LLM extraction is optional and disabled by default. It runs only when:

1. Local confirmed products, cache, Open Facts, and UPCItemDB miss.
2. Web search finds a candidate page.
3. JSON-LD, embedded JSON, and Open Graph extraction all fail.
4. `ENABLE_LLM_FALLBACK=true` and provider configuration is present.

The service strips scripts/styles and limits visible page text before sending it
to an OpenAI-compatible chat-completions endpoint. The provider must return
strict JSON matching the normalized product schema. Invalid JSON, missing names,
or `found=false` responses are ignored.

Configuration:

```text
ENABLE_LLM_FALLBACK=false
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=
LLM_MODEL=
LLM_MAX_PAGE_CHARS=12000
```

LLM results:

- use `source=llm_fallback`
- use confidence `0.35` when the model saw the exact barcode
- use confidence `0.25` when the model did not see the exact barcode
- are capped at `0.20` for search-title/product-name conflicts
- are not cached with the default `CACHE_MIN_CONFIDENCE=0.7`
- cannot override confirmed local products because local products are checked first
- can still prefill Grocy's editable product form

Only enable this after selecting a provider and accepting that limited retailer
page text will be sent to that provider.
