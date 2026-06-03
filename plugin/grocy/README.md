# Grocy Plugin Wrapper

This folder contains the thin Grocy barcode lookup plugin wrapper.

Behavior:

1. Grocy calls `UltimateBarcodeLookupPlugin.php`.
2. The plugin calls the external lookup service.
3. The plugin maps the normalized response back into Grocy's expected format.

The actual lookup logic belongs in the FastAPI service, not in this plugin.

## Install

```bash
./install.sh /home/service/grocy/config/data/plugins
```

Then set Grocy's `data/config.php` setting:

```php
Setting('STOCK_BARCODE_LOOKUP_PLUGIN', 'UltimateBarcodeLookupPlugin');
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
