---
status: pending
priority: P2
filed: 2026-09-30
source: plan 186-14 pass 1 review fixes
---

# ic_measure resumes at (job, tf) grain and pays a digest pass before every skip decision

## What

After pass 1 a unit is (job, tf) and owns its whole scope. Three consequences:

- A kill during a unit's compute loses that unit's computed cells (before, the loss was one feature block).
- Every run, even one that skips every unit, makes one fetch-and-digest pass over the whole feature family (column digests and family completeness) before the skip decision.
- A `--start` later than a prior real run leaves that run's earlier `member_window` rows outside the new DELETE range (the DELETE is bounded by the spec's time range).

## What to do

After todo 469 fixes the bootstrap cost, measure both costs on the rebuilt features. If the digest pass matters, cache column digests keyed by the feature table's content watermark; if resume loss matters, checkpoint per-block score rows (small) under the unit key. Refuse, rather than allow, a `--start` that differs from the prior completed unit's range_start for the same unit_key.
