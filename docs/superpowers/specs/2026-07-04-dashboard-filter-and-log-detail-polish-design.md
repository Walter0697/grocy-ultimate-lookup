# Dashboard Filter And Log Detail Polish Design

## Goal

Improve the visual treatment of the dashboard scan filters and the log detail
dialog so both feel more intentional and easier to scan.

## Scope

This feature adds:

- a lighter soft-pill treatment for the dashboard scan filter row
- a more readable diff-panel layout for the log detail dialog

This feature does not add:

- new filter behavior
- new log data fields
- new dialog actions

## Product Decisions

### Dashboard filters should feel like filters, not navigation

The `All`, `Needs review`, `Applied`, and `Failed` row currently reads too
close to the top-level page tabs. The new treatment should clearly read as a
secondary filter control.

### Chosen direction: Soft Pills

Use rounded pill buttons with:

- a dark active state
- light inactive pills with soft borders
- quieter count badges
- more spacing between pills than the current segmented strip

This keeps the filter row lightweight and distinct from the main page nav.

### Log detail should be readable before it is dense

The current detail presentation is too close to a compact inspector. Since the
dialog is for inspection rather than scanning dozens of rows, it should have a
bit more breathing room.

### Chosen direction: Readable Diff Panel

Use a stacked diff-panel layout with:

- compact metadata chips at the top
- one bordered diff block per changed field
- a clear `before -> after` presentation
- moderate spacing, not a fully dense audit ledger

## UX Design

### Dashboard filter row

Keep the filter row in the same location under the topbar, but change its
visual style to:

- pill-shaped buttons instead of a continuous segmented strip
- a narrower visual footprint
- softer inactive emphasis
- a more distinct active count badge

### Log detail dialog

Keep the existing dialog trigger behavior, but restyle the content to:

- show source/time and product title first
- follow with barcode, product id, and source as compact chips
- render each changed field as an individual diff card

## Implementation Notes

- reuse the existing dashboard filter click behavior
- reuse the existing log detail data payload
- keep HTML changes small; most of the change should be in CSS and light
  template reshaping

## Testing

Implementation should cover:

- static HTML/JS coverage confirming the filter row still exposes the same
  buttons and state ids
- static HTML coverage for the log detail dialog structure
- focused manual browser verification after container rebuild
