---
status: pending
priority: P2
filed: 2026-11-24
source: indicagent-3d, todo 470 merged into 471 (ruled by the lead 2026-11-24)
---

# ic_measure resumes at (job, tf) grain: a kill loses the whole unit, and every run pays a digest pass

## What

(Todo 470, merged.) A unit is (job, tf) and owns its whole scope: a kill loses its computed cells, and every run makes one fetch-and-digest pass over the whole feature family before the skip decision. At 1d this is small (a unit about two to five minutes, the digest pass about 40 percent of a 7-minute 925-name run, measured 2026-09-30; about 1.5 hours at the 12,857-name universe by linear scaling, not measured). At the intraday tfs a unit is hours (15m about 15 hours and 5m about 45 hours by the same scaling, order of magnitude only), so a kill is unaffordable. The `--start` orphan-row defect is fixed (review fix F2, 2026-09-30).

## Done when

Score rows are checkpointed per horizon or per feature block under the unit key and a resume skips the completed ones, and the column digests are cached by the feature table's content watermark if the digest pass is measured to matter (it is measured on the 25 pilot names after the block 2 rerun, light). Resume gives the same rows as an uninterrupted run (a test kills a unit mid-way and compares).

Prerequisite of the scope-all pin; does not block the scope-1d pin. Related: 667 (time-chunk mode), 471 (width ruling).
