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
