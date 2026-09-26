

## Unified design note

Unified design (2026-09-26): the `context_features` table is summarized and dropped in phase 186; any future LLM-scored context feature is a `feature_vectors` column built by the rebuilt batch path and enters books as a family member. The gate (a running I8 stack) is unchanged.
