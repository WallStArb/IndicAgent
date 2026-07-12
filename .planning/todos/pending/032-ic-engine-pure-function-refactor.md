---
status: merged
merged_into: 009
merged_date: 2026-07-12
---

# 032 — ic_engine Pure Function Extraction

**Merged into `.planning/todos/pending/009-service-utils-ic-engine-cleanup.md` (Part E)
2026-07-12** — housekeeping consolidation. This todo, 009, and 012 were all explicitly gated on
the same "Phase B cleanup sprint," and 032's own text said "Related: 009... can be done in the
same sprint." Verified against live code as part of the merge: 2 of the 3 originally-proposed
extractions (`compute_ic_for_window`, `apply_corpus_fdr`) already shipped via todo 048's
`src/intelligence/statistics/ic_math.py` — only `build_walk_forward_folds` remains outstanding,
see 009 Part E for the corrected, narrower scope. This file kept as a pointer so old references
don't 404.
