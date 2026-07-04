# Auto-Created Product Edit Design

Date: 2026-06-28

## Summary

Add a dashboard edit flow for products that were auto-created by this service from lookup results. The flow updates the Grocy product in place and does not attempt stock reversal, barcode remapping, or correction of pre-existing Grocy products.

This keeps the dashboard focused on fixing service-created product metadata while leaving general product management to Grocy.

## Goals

- Let a user fix a wrong auto-created product directly in the lookup dashboard
- Reuse the existing Grocy product update capabilities already present in the service
- Avoid changing stock history or scan history during product edits
- Avoid exposing general editing for all Grocy products

## Non-Goals

- Reversing previously applied stock operations
- Moving a barcode from one product to another
- Merging products
- Editing Grocy products that were not auto-created by this service
- Building a general-purpose Grocy product editor

## Scope Boundary

The dashboard edit flow is only for products created by this service through the trusted auto-create path.

If a barcode already mapped to an existing Grocy product before the scan, that product remains read-only in this dashboard. The user should edit it in Grocy itself.

## User Experience

### Product List

The dashboard product list will show an `Edit` action only for products that are eligible for service-side editing.

Non-eligible products show no edit action. Optionally, the UI may later add a passive hint such as `Edit in Grocy`, but that is not required for the first implementation.

### Edit Flow

1. The user opens the dashboard products view.
2. For an eligible auto-created product, the user clicks `Edit`.
3. The dashboard opens a form prefilled with the current product state.
4. The user updates product information.
5. The dashboard saves the changes through this service.
6. The product card refreshes to show the updated metadata.

### Editable Fields

The initial edit form should support the same product fields already supported by the dashboard confirmation flow:

- product name
- brand
- package quantity
- image URL
- uploaded image override
- description
- default location
- stock quantity unit
- purchase quantity unit
- purchase-to-stock conversion factor

This keeps product creation and product editing aligned.

## Behavior

### What Editing Does

Editing updates the existing Grocy product in place using the current product ID and barcode.

The update includes:

- core product fields in Grocy
- barcode row quantity unit for the attached barcode
- product-specific quantity unit conversions when needed
- product picture when the image URL changes or an upload is selected

### What Editing Does Not Do

Editing does not:

- reverse stock already added or removed by earlier scans
- create a new product as part of the edit flow
- re-run lookup matching
- detach the barcode from the current product
- change scan event history

If the auto-created match was conceptually the wrong item but the user only wants to correct the displayed product information, this flow is sufficient. If the user actually needs barcode reassignment or stock correction, that is a separate future feature.

## Eligibility Model

The service needs a durable way to identify which Grocy products it owns for dashboard editing.

### Problem

Today the service records local confirmed-product data and notes when auto-creating from lookup results, but that is not a reliable ownership model for deciding whether an arbitrary Grocy product should be editable in the dashboard.

### Design

Add a local product ownership registry that records:

- Grocy product ID
- barcode
- creation source
- created-at timestamp

The registry is written only when the service auto-creates a product from the trusted lookup path.

The dashboard edit action is shown only when the current Grocy product ID is present in that registry and marked as `auto_created`.

### Why Local Ownership Instead of Grocy Description Parsing

Using a dedicated local registry is preferred over parsing Grocy description text or notes because:

- description text is user-editable
- format changes would silently break eligibility checks
- ownership should be an explicit machine-level decision

## Backend Design

### Data

Add a small local store for editable auto-created products. SQLite is preferred to match the existing local stores in this service.

Suggested schema:

- `product_id` integer primary key
- `barcode` text not null
- `source` text not null
- `created_at` timestamp not null default current timestamp
- `updated_at` timestamp not null default current timestamp

The store supports:

- record auto-created product ownership
- fetch ownership by product ID
- fetch ownership by barcode if needed
- remove stale ownership records if a product no longer exists

### Auto-Create Path

When `_create_from_lookup` successfully creates a Grocy product, the service records the new product ID in the ownership store.

This is the only path that grants dashboard edit eligibility.

### Read Path

The dashboard product response should include an `editable` boolean derived from the ownership store.

That lets the frontend decide whether to render the `Edit` action without duplicating business rules.

### Write Path

Add an endpoint for editing dashboard-owned products, for example:

- `PUT /dashboard/products/{product_id}`

Request body should mirror the current `PendingProductConfirmation` shape closely enough to reuse validation and Grocy update logic.

Server behavior:

1. Load ownership record for `product_id`
2. Reject if not dashboard-editable
3. Load current Grocy product
4. Reuse Grocy update logic with the product ID and recorded barcode
5. Return the updated dashboard product card

### Error Handling

The endpoint should return:

- `404` if the product no longer exists in Grocy
- `403` or `400` if the product is not dashboard-editable
- `422` for invalid field input
- `502` or `500` for Grocy update failures, preserving a useful message

## Frontend Design

### Product Card

Add an `Edit` button to dashboard product cards only when `editable` is true.

### Edit Modal

Use a modal or drawer that closely matches the existing scan confirmation form.

Prefill the form from the current product card plus any extra product details returned by the edit/read endpoint as needed.

### Shared Form Logic

The current dashboard already supports:

- image uploads
- location selection
- quantity unit selection
- purchase-to-stock conversion fields

The edit form should reuse as much of that logic as possible to reduce drift between create and edit behavior.

### Save Result

On success:

- close the editor
- refresh the products view
- show a short success toast

On failure:

- keep the editor open
- show the API error

## API Shape

### Product List Response

Extend the dashboard products payload with:

- `editable: boolean`

### Product Edit Request

Use the existing dashboard product-edit field set:

- `name`
- `description`
- `brand`
- `quantity`
- `image_url`
- `location_id`
- `qu_id_stock`
- `qu_id_purchase`
- `qu_factor_purchase_to_stock`

### Product Edit Response

Return the updated product card with the latest Grocy-backed values and `editable: true`.

## Testing

### Backend Tests

- ownership registry records auto-created products
- non-auto-created products are not editable
- dashboard product listing marks editable products correctly
- product edit endpoint rejects unknown or non-owned products
- product edit endpoint updates owned products through Grocy client
- product edit preserves barcode linkage
- product edit updates quantity unit conversions correctly

### Frontend Tests

- edit button renders only for editable products
- edit modal prepopulates fields
- successful save refreshes product list
- API failure keeps modal open and displays error

## Risks

### Ownership Drift

If Grocy products are deleted or changed outside this service, the ownership registry may become stale. The implementation should tolerate this by returning `404` and optionally pruning stale records when detected.

### Partial Product Data in Product Cards

The existing dashboard product card may not include every field required for editing. If so, the backend should expose a product-detail endpoint for editable products or extend the existing products payload enough to prefill the edit form safely.

### Future Scope Pressure

Users may expect `Edit` to also fix incorrect stock history or remap barcodes. The UI should be explicit that this first version edits product information only.

## Recommended Implementation Order

1. Add ownership store for auto-created products
2. Record ownership during trusted auto-create
3. Extend dashboard product responses with `editable`
4. Add backend update endpoint for editable products
5. Add dashboard `Edit` action and editor UI
6. Add tests for ownership, API behavior, and UI conditions

## Open Decisions Resolved

- Edit scope is limited to products auto-created by this service
- Existing Grocy products remain editable only in Grocy
- Product edits update metadata in place
- Stock reversal and barcode remapping are out of scope for this implementation
