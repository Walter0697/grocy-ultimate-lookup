# Grocy Plugin Wrapper

This folder contains the thin Grocy barcode lookup plugin wrapper.

Behavior:

1. Grocy calls `UltimateBarcodeLookupPlugin.php`.
2. The plugin calls the external lookup service.
3. The plugin maps the normalized response back into Grocy's expected format.

The actual lookup logic belongs in the FastAPI service, not in this plugin.

## Install

From this folder:

```bash
./install.sh /home/service/grocy/config/data/plugins
```

Then set Grocy's `data/config.php` setting:

```php
Setting('STOCK_BARCODE_LOOKUP_PLUGIN', 'UltimateBarcodeLookupPlugin');
```

Restart Grocy after changing `config.php` or replacing the plugin:

```bash
docker compose -f /home/service/grocy/docker-compose.yml restart grocy
```

The Grocy container must be able to reach the lookup service. With the current
Docker setup, Grocy uses:

```text
http://host.docker.internal:9290
```

That requires this in Grocy's compose service:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

## Plugin Settings

The plugin reads optional environment variables from the Grocy container:

```text
ULTIMATE_LOOKUP_URL=http://host.docker.internal:9290
ULTIMATE_LOOKUP_APPEND_SOURCE_MARKER=false
```

`ULTIMATE_LOOKUP_URL` points Grocy at the external FastAPI lookup service.

`ULTIMATE_LOOKUP_APPEND_SOURCE_MARKER` is disabled by default. If set to `true`,
`yes`, or `1`, product names are returned with the source appended, for example:

```text
Tomato Ketchup [open_food_facts]
```

Keep this disabled for normal use. Source metadata is available from the
external lookup API response when you need to inspect provenance.

## Metadata Handling

The plugin sends Grocy only the fields Grocy needs to prefill the product form:

- `name`
- `location_id`
- `qu_id_purchase`
- `qu_id_stock`
- `__qu_factor_purchase_to_stock`
- `__barcode`
- `__image_url`
- `description`

The description contains a concise provenance summary when available:

- original and alternate-language names
- brand and quantity
- lookup source, name origin, confidence, and English-name research status
- barcode and source URL

Grocy's product save path can try to persist unknown keys as product columns,
so the plugin response must stay limited to Grocy-supported fields.

The external lookup service keeps the full raw source payload in its own cache.
Use the service API directly when you need provenance:

```bash
curl -sS 'http://localhost:9290/lookup/067489302124?use_cache=false'
```

This keeps Grocy as the inventory system and keeps lookup provenance in the
lookup service.

## Verify

Check that the external service is healthy:

```bash
curl -sS http://localhost:9290/health
```

Check lookup directly through the service:

```bash
curl -sS 'http://localhost:9290/lookup/057000013165?use_cache=false'
```

Check lookup through Grocy's external barcode endpoint:

```bash
curl -sS 'http://localhost:9283/api/stock/barcodes/external-lookup/057000013165'
```

Expected behavior:

- Known barcodes return a product object.
- Unknown barcodes return `null`.
- Grocy's UI fills the fields but still lets you edit them before saving.

## Troubleshooting

If Grocy returns `null` for everything:

- Confirm the lookup service is running with `docker compose ps`.
- Confirm `curl -sS http://localhost:9290/health` returns `{"status":"ok"}`.
- Confirm Grocy has `extra_hosts: ["host.docker.internal:host-gateway"]`.
- Confirm the plugin file exists in Grocy's persistent plugin folder.
- Confirm `STOCK_BARCODE_LOOKUP_PLUGIN` is set to `UltimateBarcodeLookupPlugin`.
- Restart Grocy after installing or replacing the plugin.

If direct service lookup works but Grocy lookup fails:

- Exec into the Grocy container and test `http://host.docker.internal:9290/health`.
- Check whether your Grocy compose file overrides container DNS or networking.
- Set `ULTIMATE_LOOKUP_URL` explicitly in the Grocy container environment.

If Grocy returns an older verbose product name:

- The lookup service may have an old cached row.
- Current service versions ignore stale cache rows without `normalized_name`.
- Run direct lookup with `use_cache=false` to force a fresh external source read.

If image URLs are missing:

- The external source probably did not provide an image.
- Grocy lookup still works; the image field is optional.
