---
phase: 187-research-core-recipe-book-selection-construction
plan: 08
status: complete
completed: 2026-10-27
commits: [59c6c44fb, 44409aafb, 34af081ca, 7daede4b7]
requirements: [R-187-14, R-187-15]
---

# 187-08 summary: horizon rule and the E17 memory rule for fitted books

- Task 1 (59c6c44fb): `horizon.HorizonRule(kappa)`, causal partial adjustment that closes a
  name out to exactly 0 after `reach_rows` flat rows, read-only output for every kappa;
  `book.book_memory()` = member memory (with a daily target's reach) + combiner and horizon
  reach, rounded once; optional `BookSpec.horizon_rule` (kappa < 1; the identity is unset).
- Task 2 (44409aafb, 34af081ca): ridge and kappa cells in the E17 battery, appended so
  positional seeds do not move, existing cells bit-equal at a fixed seed; `--sessions` on the
  driver. Report: `187-08-BATTERY.md`.
- Task 3: `run_book`, the power check and the shift diagnostic read L from one `book_memory()`;
  `book_timing` applies the horizon rule; book records carry `memory`. A ridge or smoothed book
  runs for real only under `research/certificates/e17_fitted_books.json`
  (`certificate.py`, written by `scripts/research/certify_fitted_books.py`): admitted are ridge
  at book_v1's configuration and kappa 0.2; refused are kappa 0.5, ridge with kappa and any
  uncertified setting. Ledger: E17 amendment for fitted books.

Deviations: the battery is judged at 4,000 sessions (the owner's StepM standard, applied here);
the certificate is a per-definition code fingerprint, not a hand-written constant (review
amendment); production passes no tradable mask (review); book_memory_rows stays as
book_memory's helper. Verification: full unit suite, repro_frozen bit-identical, two code
reviews.

Open: the per-cell 99% bound across many cells (raised for the owner with the StepM battery).
