---
status: pending
priority: P2
filed: 2026-11-18
source: E17 amendment 2026-11-18 (b), todo 638
owner: lead
---

# Recertify the fitted-book certificate after the E17 memory fix

## What

`research/certificates/e17_fitted_books.json` fingerprints `timing.e17_memory` and `book.book_memory`, which the E17 memory fix edited, so the certificate is void on purpose: a fitted book (ridge combiner or horizon kappa below 1) is refused for a real run until it is recertified. Book memory is unchanged for every existing spec, so the rerun should reproduce the voided counts.

## Done when

`scripts/research/certify_fitted_books.py` runs from a fresh battery record on the current code and writes the new certificate; its cells hold size as before; a note records that the counts match the voided certificate.

## Not blocking

No first counted family uses a fitted book (the daily residual and seasonality families are equal weight).
