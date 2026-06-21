# Community Catalog Positioning

Grocy Ultimate Lookup uses public product databases first whenever they have a
good answer. Open Food Facts, Open Products Facts, Open Beauty Facts, Open Pet
Food Facts, and similar projects are not competitors to this project. They are
part of the lookup chain, and they are the preferred public commons for product
facts when their records are complete enough for a barcode.

The community catalog exists because real pantry scanning still has gaps. If
public databases already had exactly the product identity, image, language,
region, and household-use fields needed for every item, Grocy Ultimate Lookup
would not need a catalog system.

In practice, users scan many items that are missing, ambiguous, region-specific,
or outside the strongest coverage area of public databases. Household scanning
also cares about practical Grocy behavior: the display name a user wants, the
image that should appear in the dashboard, and the confidence needed before a
stock operation can proceed.

## Why Catalogs Help

Barcodes are not always globally clean in real use. Duplicate or ambiguous
barcode records can happen, especially across regions, imported products,
private-label products, multipacks, or retailer-specific packaging.

A GitHub catalog can be scoped by shopping pattern or community. One catalog
might focus on Japanese products, another on Korean products, and another on a
specific local store. A user who usually shops in one context can prioritize the
catalogs that match that context, reducing the chance of accepting the wrong
duplicate record.

The catalog is also intentionally simple. It stores confirmed product records in
a portable folder structure:

```text
products/
  627/
    985/
      627985000070/
        product.json
        image.jpg
```

That makes it easy for a normal GitHub repository to become a shareable
reference source without running a central service.

## How It Fits The Lookup Goal

This project is an "ultimate lookup" service for Grocy workflows. It combines
multiple deterministic providers, community catalogs, web search, optional LLM
page extraction, and Codex-based research fallback to fill as many lookup gaps
as possible.

The catalog is one source in that chain, not the whole system. It is useful when
public databases miss, when a local community has better regional knowledge, or
when the right Grocy-ready result differs from a generic public product record.

## Relationship To Open Databases

The long-term direction should be cooperative. A confirmed catalog record can be
used immediately by Grocy, and later it can become a candidate for contribution
to an open product database.

That upstream path should be deliberate. Open databases need clean, structured,
public-quality data. Grocy Ultimate Lookup should not blindly push every local
confirmation upstream, because that could pollute public databases with partial
or context-specific records.

A future contribution workflow can review a catalog record, show missing fields,
map known fields into the target database format, and ask the user to approve
the submission. In that model, the GitHub catalog becomes a staging and review
queue for better public data, while still solving the immediate Grocy lookup
problem.
