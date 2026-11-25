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

## Design notes 2026-11-24 (indicagent-fb; no code edited)

Today a unit is (job, tf) and `execute_unit` calls `unit.compute()` for all rows, then one `bulk_load` replaces the prior identity (`services/ic_measure.py:909`); a completed identity is skipped before any compute (`completed_provenance_batch`). A finer grain has to keep that single-writer, replace-where contract, so a checkpoint is a compute cache, not a partial write to the result table.

Proposed mechanism: a per-unit spool of finished cells.
1. Cell grain: one (horizon, feature block) cell of the scan (`feature_blocks`, `scan_family`). After a cell's rows are computed (`_sorted_rows` order), write them to a spool file under `logs/` keyed by the unit key, the cell's horizon and block names, and the input digests the unit already computes (`column_digest`, `features_digest`, `panels_digest`, `labels_digest`); a cell file is valid only for its own digests, so a changed input recomputes it and never reuses a stale one.
2. Resume: `unit.compute()` loads each valid cell file and computes the rest, then assembles the same row list in the same order and hands it to the one `bulk_load`. Resume therefore gives the same rows as an uninterrupted run by construction, and the test is a kill mid-unit against a full run compared row for row.
3. The digest pass (todo 470's other half): cache `column_digest` per column keyed by the feature table's content watermark, only if the pilot measurement shows the pass matters (about 40 percent of a 25-name 1d run at 925 names; light at 25). A wrong cached digest would let a changed column pass as unchanged, so the watermark must be a content digest of the stored column range (the month-granular `bar_content_digests` pattern), never a row count or a timestamp.
4. 667 interaction: with the strided-row gather, the cell grain moves to (horizon, chunk, block); the spool key adds the chunk, and pass 1's mask is itself a cached cell.

Spool cleanup follows the clean-as-you-go rule: a unit's spool is deleted once its `bulk_load` completes. Failure mode to test: a spool file from a killed write (partial) must fail its digest and recompute, not load.
