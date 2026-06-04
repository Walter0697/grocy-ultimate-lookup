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

Web-derived results use low confidence, currently `0.55`, but can still be
returned as the best lookup result. This lets Grocy prefill the editable product
form. If the web result is wrong, edit it before saving in Grocy.

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
    "confidence": 0.55,
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
