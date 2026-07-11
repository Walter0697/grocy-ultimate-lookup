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
- Ephemeral Codex coding-agent research fallback

## Run

```bash
cp .env.example .env
docker compose up -d
```

Service:

```text
http://localhost:9290/lookup/057000013165
```

Dashboard:

```text
http://localhost:9290/
```

## External Scanner Dashboard

The external scanner API checks Grocy first. Existing Grocy barcode mappings
are authoritative and immediately receive the requested stock operation.
Unknown barcodes run through Ultimate Lookup and become pending dashboard cards
for review.

For a Pi/ESP-style device, prefer the device-friendly endpoint. The service
generates the event ID and returns a compact response:

```bash
curl -sS -X POST 'http://localhost:9290/scanner/scan' \
  -H 'Content-Type: application/json' \
  -H 'X-Scanner-Token: secret-token' \
  -d '{
    "device_id": "kitchen-pi",
    "barcode": "066200032500",
    "mode": "add",
    "quantity": 1,
    "location_id": 2
  }'
```

Prototype a USB barcode scanner on Linux/Raspberry Pi:

```bash
python3 scripts/device_scanner.py \
  --server http://localhost:9290 \
  --device-id kitchen-pi \
  --token secret-token \
  --input-mode auto \
  --scanner-device auto \
  --state-file /tmp/grocy-scanner-state.json
```

On Linux, `--input-mode auto` first tries to bind a likely scanner from
`/dev/input/by-id` or `/dev/input/event*` so the scanner can feed the script
without stealing your normal keyboard. If auto-detection finds nothing, the
script falls back to the existing stdin loop. Use `--list-input-devices` to
inspect candidates, or pass a specific event device with `--scanner-device`.

With `--state-file`, the scanner reloads mode, quantity, and location from JSON
before every barcode. This lets buttons or a separate control process update
behavior without restarting the scanner. The scanner script sends a heartbeat
at startup and after successful scans.

Update the scanner state from another terminal:

```bash
python3 scripts/scanner_statectl.py \
  --state-file /tmp/grocy-scanner-state.json \
  --mode add \
  --quantity 1 \
  --location-id 2 \
  --location-name Fridge
```

Run an interactive keyboard control loop for the same state file:

```bash
python3 scripts/scanner_statectl.py \
  --server http://localhost:9290 \
  --state-file /tmp/grocy-scanner-state.json \
  --interactive
```

`keyboard_scanner.py` is a convenience wrapper for the same state-file control
loop:

```bash
python3 scripts/keyboard_scanner.py \
  --server http://localhost:9290 \
  --state-file /tmp/grocy-scanner-state.json
```

Keyboard commands:

- `a`: add mode
- `r`: remove mode
- `s`: set/manage mode
- `+`: quantity up
- `-`: quantity down
- `l`: cycle Grocy location
- `?`: show current state

Barcode input should go to `device_scanner.py`. Keyboard, GPIO, or another
control process should only update the shared state file that `device_scanner.py`
reads before each scan.

For full Raspberry Pi service setup instructions, see
`docs/pi-scanner-setup.md`.

For the ESP32 direction, especially with a USB barcode scanner, see
`docs/esp32-scanner-plan.md`.

For Raspberry Pi buttons, map pins to state actions in JSON and run the GPIO
controller beside `device_scanner.py`:

```bash
cp scanner-buttons.example.json scanner-buttons.json
python3 scripts/gpio_state_controller.py \
  --config scanner-buttons.json \
  --server http://localhost:9290
```

The controller supports direct mode buttons, quantity buttons, and location
cycling:

- `mode` with value `add`, `remove`, or `set`
- `quantity_delta` with value `1` or `-1`
- `quantity_set` with value `0`
- `location_next`

You can test the same JSON mapping without GPIO hardware by using `--stdin`.
Type a control name like `mode_add`, or its configured `key` such as `a`, `+`,
`0`, or `l`:

```bash
python3 scripts/gpio_state_controller.py \
  --config scanner-buttons.example.json \
  --server http://localhost:9290 \
  --stdin
```

For manual/idempotent integrations, send a scanner event with your own event ID:

```bash
curl -sS -X POST 'http://localhost:9290/scan-events' \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": "kitchen-pi-000001",
    "device_id": "kitchen-pi",
    "barcode": "055966908051",
    "mode": "add",
    "quantity": 1,
    "location_id": 2
  }'
```

Supported modes:

- `add`: purchase/add the quantity to Grocy stock
- `remove`: consume/remove the quantity from Grocy stock
- `set`: inventory the product to the exact quantity, including zero

`location_id` is optional. When supplied, it is forwarded to Grocy for add,
remove, and set operations. When omitted, Grocy uses the product/default stock
location behavior. Hardware clients should fetch available locations from
`GET /dashboard/options` and send the stable numeric ID instead of a location
name.

Every hardware retry must reuse the same `event_id`. Duplicate event IDs return
the original event and never apply the stock operation twice.

Unknown items remain `pending` or `researching`. The dashboard allows editing
the product name, description, image, location, and quantity unit. Confirmation
creates the product and barcode in Grocy, saves the confirmed lookup locally,
and applies the original pending stock operation.

When confirming a new product, the dashboard can also set Grocy's purchase to
stock conversion. This is intended for cases like scanning one bag that should
add multiple stock units, for example one scanned package adding 12 boxes. The
conversion is stored in Grocy and existing Grocy products keep using whatever
Grocy already has configured. Later conversion edits belong in Grocy.

## Community Catalog Export

Manual product confirmations can also be exported as portable JSON records.
This is intended for a federated catalog flow: each user can keep their own
GitHub repository of confirmed products, and future versions can read other
people's repositories as reference catalogs.

The community catalog is not intended to compete with Open Food Facts, Open
Products Facts, Open Beauty Facts, or similar public databases. Those projects
are the right place for public product data when they already have the fields
and coverage needed for a barcode. Grocy Ultimate Lookup adds a catalog layer
because real household scanning still has gaps: sparse non-food coverage,
regional products, retailer-specific items, duplicate or ambiguous barcodes,
and Grocy-specific naming/image preferences.

Catalogs are therefore a scanner-ready bridge. A user can keep a personal or
community catalog for the stores and regions they actually shop in, while still
using Open Facts and other providers first when they have a reliable match. In
the future, catalog records can also become a review queue for contributing
cleaner data upstream to open product databases, with user approval and quality
checks so public databases are not polluted.

For the longer rationale, see `docs/community-catalog-positioning.md`.

Open `http://localhost:9290/settings` to configure export from the web UI.
Settings are saved in SQLite at `APP_SETTINGS_PATH` and take effect without a
container restart. Environment variables remain defaults for first startup:

Grocy units are authoritative. The Settings page can seed a shared built-in
unit list into Grocy, and later scan confirmation reuses those seeded Grocy
units instead of maintaining a separate app-specific unit catalog.

```text
COMMUNITY_CATALOG_ENABLED=true
COMMUNITY_CATALOG_PATH=/data/community-catalog
COMMUNITY_CATALOG_EXPORT_IMAGES=false
COMMUNITY_CATALOG_AUTO_COMMIT=false
COMMUNITY_CATALOG_AUTO_PUSH=false
COMMUNITY_CATALOG_GIT_REMOTE=origin
COMMUNITY_CATALOG_GIT_BRANCH=main
COMMUNITY_CATALOG_AUTHOR_NAME=Grocy Ultimate Lookup
COMMUNITY_CATALOG_AUTHOR_EMAIL=grocy-lookup@example.local
```

When enabled, user-confirmed products are exported. You can separately allow
auto-pushing AI-searched results and auto-pushing later dashboard edits of an
existing product. Modified-product exports are marked as `source:
user_modified`, and when Grocy Ultimate Lookup knows the upstream origin it
also records `original_source` in `product.json`.

Records are written using two three-digit shards plus the full barcode folder:

```text
products/
  627/
    985/
      627985000070/
        product.json
        image.jpg
```

`product.json` stores the confirmed product fields and `source:
user_confirmed`. If `COMMUNITY_CATALOG_EXPORT_IMAGES=true` and the confirmed
product has an image URL, the service also attempts to download `image.jpg`.
Image download, Git commit, and Git push failures are logged as warnings and do
not block Grocy product creation or stock updates.

The dashboard uses one newest-first Gallery Wall:

- applied scans are solid Polaroid cards and require no interaction
- researching, uncertain, unknown, and failed scans are dotted review cards
- selecting a dotted card opens the product review drawer
- the compact header scanner accepts a barcode and Enter
- barcode preview checks Grocy first, then Ultimate Lookup, without changing stock
- complete trusted lookup matches are created in Grocy automatically before preview; trusted means name, image, no lookup warnings, and confidence at or above `AUTO_CREATE_MIN_CONFIDENCE` (default `0.8`)
- the preview popup selects add/remove/manage, quantity, and location before confirmation
- lookup and Grocy write controls show progress and prevent duplicate submissions while requests run
- set-mode submissions require explicit browser confirmation

Preview a barcode without creating a scan event or changing stock:

```bash
curl -sS 'http://localhost:9290/scan-preview/055966908051'
```

Scanner configuration:

```text
SCAN_EVENTS_PATH=/data/scan-events.sqlite3
GUL_API_KEY=
SCANNER_DEVICE_TOKENS=kitchen-pi:secret-token
SCANNER_DEVICE_OFFLINE_AFTER_SECONDS=120
GROCY_URL=http://host.docker.internal:9283/api
GROCY_PUBLIC_URL=http://localhost:9283
GROCY_API_KEY=
```

Set `GROCY_API_KEY` when Grocy authentication is enabled. Set
`SCANNER_DEVICE_TOKENS` to require `X-Scanner-Token` for `/scanner/scan` and
`/scanner/heartbeat`. Leave it empty for local unauthenticated testing. Multiple
devices use comma-separated `device_id:token` pairs.

Set `GUL_API_KEY` to protect the dedicated integration endpoints under `/external/*`
with `X-GUL-API-Key`. The normal dashboard pages and browser-driven dashboard
API remain unchanged, while external tools such as the Grocy Telegram agent can
use the protected external-integration namespace:

- `GET /external/scan-events`
- `GET /external/scan-events/{event_id}`
- `POST /external/scan-events/{event_id}/image`
- `GET /external/dashboard/products`
- `POST /external/dashboard/products/{product_id}/request-image-review`

## Response Shape

```json
{
  "barcode": "057000013165",
  "found": true,
  "result": {
    "barcode": "057000013165",
    "name": "Heinz Tomato Ketchup",
    "name_language": "en",
    "name_origin": "sourced",
    "alternate_names": {},
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
  "candidates": [],
  "research_status": null
}
```

## Grocy Plugin

The Grocy plugin folder is intentionally small. It should only call this
service and translate the response into Grocy's expected barcode lookup format.

See `plugin/grocy/README.md`.

Default Grocy behavior:

- Product names use `normalized_name`.
- Source markers are not appended to product names.
- Lookup provenance and original-language names are added to the product description.
- Grocy's UI can still edit auto-filled fields before saving.

## Multilingual Names

Lookup names follow this priority:

1. User-confirmed local name.
2. Sourced English name from databases, retailer pages, LLM extraction, or agent research.
3. Agent-translated English name when no sourced English name exists.
4. Trusted original-language name while research is pending or translation is unavailable.

Open Facts language fields such as `product_name_en`, `product_name_fr`, and
`lang` are preserved as `name_language` and `alternate_names`. A trusted
non-English-only result starts background agent research. The agent must first
search for a sourced English name; only after that fails may it translate the
trusted original name.

Translated results use:

```json
{
  "name": "White Drawstring Kitchen Garbage Bags",
  "name_language": "en",
  "name_origin": "translated",
  "alternate_names": {
    "fr": "Sac à ordures blancs à cordons pour la cuisine"
  },
  "source": "agent_translation"
}
```

The top-level `research_status` field reports `queued`, `running`, `completed`,
`not_found`, or `failed` when a background agent job exists.

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
WEB_SEARCH_PROVIDER=duckduckgo
SEARXNG_BASE_URL=
WEB_SEARCH_MAX_QUERIES=3
WEB_SEARCH_MAX_RESULTS=5
WEB_SEARCH_FETCH_LIMIT=3
```

Raise or lower `CACHE_MIN_CONFIDENCE` to control which lookup results are cached.
Keep it above web fallback confidence if web results should remain fresh
best-effort suggestions.

`WEB_SEARCH_PROVIDER=duckduckgo` uses DuckDuckGo's HTML results directly.
Set `WEB_SEARCH_PROVIDER=searxng` and `SEARXNG_BASE_URL=http://your-searxng`
to route searches through a self-hosted SearXNG instance instead. The search
loop generates a small set of barcode-focused queries, deduplicates candidate
URLs, and fetches at most `WEB_SEARCH_FETCH_LIMIT` pages per lookup.

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

## Coding-Agent Research Fallback

The coding-agent fallback handles difficult barcodes that require multi-step
research instead of extracting one known page. It uses one fresh ephemeral Codex
CLI session per barcode and the same read-only Codex auth mount pattern used by
Pochita.

Workflow:

1. Local confirmed products, trusted cache, databases, and structured web lookup run normally.
2. If no result exists, the best result confidence is `0.45` or lower, or only
   a non-English name exists, a background agent search is queued.
3. The current Grocy request returns immediately instead of waiting for Codex.
4. Codex searches multiple sources for sourced English and returns strict product JSON.
5. If no sourced English exists, Codex may translate the persisted trusted original name.
6. The researched result is persisted in `/data/agent-search.sqlite3`.
7. A later scan uses the agent result unless a stronger sourced result is available.

Configuration:

```text
ENABLE_AGENT_SEARCH=true
AGENT_SEARCH_PATH=/data/agent-search.sqlite3
AGENT_SEARCH_AUTH_PATH=/secrets/auth.json
AGENT_SEARCH_MODEL=gpt-5.4-mini
AGENT_SEARCH_TIMEOUT_SECONDS=300
AGENT_SEARCH_TRIGGER_CONFIDENCE=0.45
```

Docker Compose mounts the host credential read-only:

```yaml
volumes:
  - ~/.codex/auth.json:/secrets/auth.json:ro
```

Inspect a job:

```bash
curl -sS 'http://localhost:9290/agent-search/810669032478'
```

Force a new search:

```bash
curl -sS -X POST 'http://localhost:9290/agent-search/810669032478'
```

Remove a researched result:

```bash
curl -sS -X DELETE 'http://localhost:9290/agent-search/810669032478'
```

Agent results use `source=agent_search`, remain editable in Grocy, and never
outrank confirmed local products or stronger database results.
