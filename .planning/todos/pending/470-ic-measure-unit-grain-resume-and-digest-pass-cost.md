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

Measured 2026-09-30 after todo 469 (pass 2), on the current features: the digest and completeness scan is
one of three fetch passes over the family and about 40 percent of a 1d run (12.6 s of 31.5 s at 100
symbols; the full 925-symbol 1d run is 7:12 in all), so a skip decision costs about three minutes at 1d and
a kill loses at most one unit of about two to five minutes. Both are small at 1d; the intraday tfs are the
open question (todo 471). Decide from the intraday measurement. The `--start` defect is independent of cost and stays.

Original plan: after todo 469 fixes the bootstrap cost, measure both costs on the rebuilt features. If the digest pass matters, cache column digests keyed by the feature table's content watermark; if resume loss matters, checkpoint per-block score rows (small) under the unit key. Refuse, rather than allow, a `--start` that differs from the prior completed unit's range_start for the same unit_key.
