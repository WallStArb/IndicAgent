

## Unified design note

Unified design (2026-09-26): the `context_features` table is summarized and dropped in phase 186; any future LLM-scored context feature is a `feature_vectors` column built by the rebuilt batch path and enters books as a family member. The gate (a running I8 stack) is unchanged.

## Status 2026-11-24 (todo consolidation pass)

Gate reworded: the old gate (I8 stack running) can never be met, since I8 was deleted in 185-45 (the body was cut to a stub in 438872b97). Deferred. LLM- or text-scored context features would enter only as a batch-built `feature_vectors` family through the counted-family queue; consider merging into `docs/ideas/signal-macro-context-layer.md`. Likely an owner idea (IDEAS.md), so kept.
