---
status: pending
priority: P2
filed: 2026-11-09
source: product review; the glossary said 324 `feature_vectors` columns while the live table has 311 (migration 577 dropped 13)
---

# Numbers that change must be generated or CI-checked, not typed into docs

## What

Hand-typed counts drift: the glossary column count was wrong after migration 577, and the handoff carried a stale disk figure (144 GB against 715 GB free). Pick the few load-bearing numbers (feature_vectors column count, active instruments, pre-2016 5m coverage, free disk) and either generate them into the docs or add a CI check that compares the typed value with the schema or a pinned query.

## Approach

Smallest first: a unit test that reads the glossary's `feature_vectors` column count and compares it with the kernel schema in `src/intelligence/features/` (no live database in CI). For live-only numbers (disk, coverage), keep them in dated handoff sections, never in canonical docs; a canonical doc states the rule, not today's number.
