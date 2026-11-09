---
status: closed
closed: 2026-11-09
priority: P2
filed: 2026-11-09
source: product review; the glossary said 324 `feature_vectors` columns while the live table has 311 (migration 577 dropped 13)
---

# Numbers that change must be generated or CI-checked, not typed into docs

## What

Hand-typed counts drift: the glossary column count was wrong after migration 577, and the handoff carried a stale disk figure (144 GB against 715 GB free). Pick the few load-bearing numbers (feature_vectors column count, active instruments, pre-2016 5m coverage, free disk) and either generate them into the docs or add a CI check that compares the typed value with the schema or a pinned query.

## Approach

Smallest first: a unit test that reads the glossary's `feature_vectors` column count and compares it with the kernel schema in `src/intelligence/features/` (no live database in CI). For live-only numbers (disk, coverage), keep them in dated handoff sections, never in canonical docs; a canonical doc states the rule, not today's number.

## Status

Done 2026-11-09. CI guard: `tests/unit/test_doc_schema_numbers.py` derives the
code truth (311 from `feature_vectors_columns()`, 288 from
`dataclasses.fields(FeatureVector)`) and asserts it against the numbers three
evergreen docs type, naming the file:line on failure. Survey: 3 checkable
claims guarded (glossary feature_vectors entry, canonical-truth-registry route
row, business-requirements Stage 0 row); 2 corrected (canonical-truth-registry
54 -> 311 and its deleted IC Engine clause; business-requirements 298 -> 288);
1 already correct (glossary 311, fixed in fb57e7a24) and now locked. DB-live
numbers (universe counts, coverage, disk) survived only in dated sections
(dated measured-state tables, dated plans, preregs) and stay unguarded by
design; historical counts (324-before-577, Phase A 50-column retellings) left
as-is. Known residual: the `FeatureVector` docstring's own prose count (300)
still lags its 288 fields; left untouched because `schemas.py` is imported by
the fingerprinted rebuild writer with runs resumable.
