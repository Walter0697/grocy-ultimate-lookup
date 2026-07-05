# Log History Search, Detail, And Barcode Audit Design

## Goal

Make the edit-history logs page behave like a real audit tool by moving search
to the server, adding a per-entry diff detail view, and adding a barcode-level
summary view.

## Scope

This feature adds:

- server-side search on the existing product edit history API
- a log detail endpoint and UI detail drawer for one history row
- a barcode audit summary endpoint and logs-page barcode summary view
- an explicit roadmap note for the deferred multi-product-per-barcode case

This feature does not add:

- undo or restore actions
- editing from the logs page
- conflict handling for one barcode linked to multiple product ids over time

## Product Decisions

### Search must be server-side

The current page-local filter is not sufficient for an audit log because it
only searches the already loaded page. Search must run on the backend so it
can work across the full dataset while staying consistent with pagination and
sorting.

### Log detail should stay out of the main table

The main logs table should remain dense and easy to scan. Full before/after
inspection should open in a detail drawer or modal instead of expanding every
row inline.

### Barcode summary should optimize for the normal case

For now the barcode audit summary should assume the normal one-barcode,
one-product mapping. Each barcode row should show the latest product name,
edit count, and most recent edit time.

## UX Design

### Logs page structure

Keep the existing top-level navigation:

- `Scan`
- `Logs`
- `Settings`

Within the logs page, add a small internal view toggle:

- `Entries`
- `Barcodes`

`Entries` remains the default.

### Entries view

The entries table keeps the current dense layout and adds:

- a search input that queries the backend
- clickable rows or a detail action that opens a diff drawer

The table columns remain:

- edited at
- product
- barcode
- product id
- changes

### Entry detail drawer

Opening a history row should show:

- edited timestamp
- barcode
- product id
- latest product name
- source
- field-by-field diff list with `before` and `after` values

This drawer is read-only.

### Barcode summary view

The barcode view should be a separate compact table showing:

- barcode
- latest product name
- edit count
- last edited time

Clicking a barcode row should filter or drill into the entry history for that
barcode. The simplest implementation is to jump back to `Entries` with the
barcode query applied.

## Backend Design

### Product edit history list API

Extend the existing `GET /product-edit-history` endpoint with:

- `query`
- existing `limit`
- existing `offset`
- existing `sort`
- existing `order`

Search surface should include:

- latest known product name
- barcode
- product id as text
- changed field names
- before values serialized as text
- after values serialized as text

The response shape should stay paginated:

- `items`
- `total`
- `limit`
- `offset`
- `sort`
- `order`
- `query`

### Product edit history detail API

Add:

- `GET /product-edit-history/{history_id}`

Response should include the full saved history row plus a frontend-friendly
diff list:

- `field`
- `before`
- `after`

This avoids repeating diff transformation logic in the browser.

### Barcode audit summary API

Add:

- `GET /product-edit-history/barcodes`

Supported query params:

- `query`
- `limit`
- `offset`
- `sort`
- `order`

Supported sort keys:

- `barcode`
- `product_name`
- `edit_count`
- `last_edited_at`

Each row should include:

- `barcode`
- `product_name`
- `edit_count`
- `last_edited_at`
- `latest_product_id`

### Store/query responsibilities

`ProductEditHistoryStore` should own:

- text search query generation
- row pagination
- grouped barcode summary queries
- single-entry lookup for detail view

`app/main.py` should stay thin and only validate request/response shapes.

## Error Handling

- unsupported sort keys return `400`
- unknown history ids return `404`
- empty search results return normal empty paginated responses
- barcode summary should not error when there is no history; it should return
  an empty result page

## Testing

Implementation should cover:

- server-side search matching product name, barcode, product id, and change
  text
- search working together with pagination metadata
- detail endpoint returning a stable diff payload
- barcode summary grouping and sorting
- logs-page script/HTML coverage for:
  - query-driven fetches
  - detail drawer wiring
  - barcode view toggle

## Roadmap Note

Deferred follow-up:

- if one barcode is linked to multiple product ids over time, add explicit
  conflict surfacing in the barcode summary instead of assuming the latest
  product snapshot is enough

That follow-up is intentionally out of scope for this implementation because
it is currently considered a rare edge case.
